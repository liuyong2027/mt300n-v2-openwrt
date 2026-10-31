#!/usr/bin/env bash
set -euo pipefail
kit="$(cd "$(dirname "$0")/.." && pwd)"
cd "$kit"
mkdir -p reports
python3 scripts/cn_rules.py
test ! -e openwrt
git init openwrt
git -C openwrt remote add origin https://github.com/openwrt/openwrt.git
git -C openwrt fetch --depth 1 origin f0a60eee2fe051741c643ea6118718aae1ef17fb
git -C openwrt checkout --detach FETCH_HEAD
cd openwrt
test "$(git rev-parse HEAD)" = f0a60eee2fe051741c643ea6118718aae1ef17fb
# Change first-boot defaults only; config_generate preserves an existing system config.
python3 - <<'PY'
from pathlib import Path
p = Path('package/base-files/files/bin/config_generate')
source = p.read_text()
for before, after in [("timezone='GMT0'", "timezone='CST-8'"),
                      ("zonename='UTC'", "zonename='Asia/Shanghai'")]:
    if source.count(before) != 1:
        raise SystemExit('Unexpected pinned timezone defaults: ' + before)
    source = source.replace(before, after)
p.write_text(source)
PY
# The release includes exact feed commits. Do not replace them with moving branches.
cp feeds.conf.default "$kit/reports/feeds.conf.lock"
./scripts/feeds update -a
./scripts/feeds install -a
python3 "$kit/scripts/patch-zerotier-init.py" "$PWD/feeds/packages/net/zerotier/files/etc/init.d/zerotier"
# Preserve ucitrack triggers while avoiding enabled probes for procd services.
# The helper refuses a different LuCI revision or unreviewed source contents.
python3 "$kit/scripts/optimize-ucitrack.py" --tree "$PWD"
cp -R "$kit/package/luci-app-zerotier-mini" package/
cp -R "$kit/package/luci-app-mango-proxy" package/
cp -R "$kit/package/mango-tcpcheck" package/
if [ -d "$kit/package/luci-app-mango-ikev2" ]; then
    cp -R "$kit/package/luci-app-mango-ikev2" package/
    chmod +x package/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-* \
        package/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2 \
        package/luci-app-mango-ikev2/root/etc/uci-defaults/9*-mango-ikev2
fi
chmod +x package/luci-app-mango-proxy/root/usr/libexec/mango-* \
    package/luci-app-mango-proxy/root/usr/libexec/rpcd/mango \
    package/luci-app-mango-proxy/root/etc/init.d/mango_* \
    package/luci-app-mango-proxy/root/etc/uci-defaults/9*-mango-*
cp -R "$kit/files" .
chmod +x package/luci-app-mango-proxy/root/etc/hotplug.d/iface/96-mango-zt-direct
chmod +x files/etc/board.d/99-mango-network
profile="${MANGO_BUILD_PROFILE:-standard}"
if [ "$profile" = ikev2 ]; then
    cp "$kit/config/mt300n-v2-ikev2.config" .config
else
    cp "$kit/config/mt300n-v2.config" .config
fi
python3 "$kit/scripts/build-profile.py" "$profile"
make defconfig
python3 "$kit/scripts/build-profile.py" "$profile" --verify
python3 "$kit/scripts/optimize-ucitrack.py" --tree "$PWD" --verify
cp .config "$kit/reports/resolved.config"
if [ "$profile" = ikev2 ]; then
    for pkg in luci luci-i18n-base-zh-cn luci-i18n-firewall-zh-cn luci-i18n-package-manager-zh-cn \
        luci-app-mango-ikev2 strongswan strongswan-minimal strongswan-swanctl \
        strongswan-mod-vici strongswan-mod-eap-mschapv2 strongswan-mod-eap-identity \
        strongswan-mod-eap-dynamic strongswan-mod-openssl \
        kmod-ipsec kmod-ipsec4 kmod-ipsec6 kmod-xfrm-interface \
        zerotier luci-app-zerotier-mini lua libuci-lua ip-full curl coreutils-base64 flock dnsmasq-full; do
        grep -qx "CONFIG_PACKAGE_${pkg}=y" .config || {
            echo "Required package was dropped by Kconfig: $pkg" >&2
            exit 1
        }
    done
    ! grep -qx 'CONFIG_PACKAGE_xray-core=y' .config
    ! grep -qx 'CONFIG_PACKAGE_luci-app-mango-proxy=y' .config
    ! grep -qx 'CONFIG_PACKAGE_dnsmasq=y' .config
else
    for pkg in luci luci-i18n-base-zh-cn luci-i18n-firewall-zh-cn luci-i18n-package-manager-zh-cn \
        xray-core luci-app-mango-proxy zerotier luci-app-zerotier-mini lua libuci-lua ip-full \
        curl coreutils-base64 flock mango-tcpcheck; do
        grep -qx "CONFIG_PACKAGE_${pkg}=y" .config || {
            echo "Required package was dropped by Kconfig: $pkg" >&2
            exit 1
        }
    done
fi
grep -qx 'CONFIG_TARGET_ramips_mt76x8_DEVICE_glinet_gl-mt300n-v2=y' .config
! grep -qx 'CONFIG_PACKAGE_luci-app-xray=y' .config
! grep -qx 'CONFIG_PACKAGE_v2ray-geoip=y' .config
! grep -qx 'CONFIG_PACKAGE_v2ray-geosite=y' .config
cp .config "$kit/reports/resolved.config"
./scripts/diffconfig.sh > "$kit/reports/diffconfig.txt"
git rev-parse HEAD > "$kit/reports/openwrt-commit.txt"
find feeds -mindepth 1 -maxdepth 1 -type d | sort | while read -r feed; do
    printf '%s ' "$feed"
    git -C "$feed" rev-parse HEAD
done > "$kit/reports/feed-commits.txt"
