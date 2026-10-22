#!/usr/bin/env python3
"""Derive a non-publishing SSR Plus+ capacity trial from the locked Release 23."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(sys.argv[1]).resolve()
RECIPE = Path(__file__).resolve().parent
SSR_COMMIT = '2abdc9aa9e19607774dc9789709212b70b8607c6'
ZT_FILES = [
    'usr/lib/mango/zt-direct.lua', 'usr/lib/mango/zt-json.lua',
    'usr/libexec/mango-zt-direct', 'usr/libexec/mango-zt-direct-run',
    'etc/hotplug.d/iface/96-mango-zt-direct',
    'etc/uci-defaults/96-mango-zt-direct', 'lib/upgrade/keep.d/mango-zt-direct',
]
def write(path, text):
    dest = ROOT / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding='utf-8', newline='\n')

def replace(path, before, after, count=1):
    p = ROOT / path
    text = p.read_text()
    assert text.count(before) == count, (path, before, text.count(before))
    p.write_text(text.replace(before, after), encoding='utf-8', newline='\n')

assert (ROOT / 'files/etc/mango-release').read_text().strip() == '23'
old = ROOT / 'package/luci-app-mango-proxy'
support = ROOT / 'package/mango-zerotier-support'
expected_helper = 'bda24368ea471e02e48508b81b1d2d3a8c3786cfd8b677cf7283d3de3657de91'
assert hashlib.sha256((old/'root/usr/libexec/mango-zt-direct-run').read_bytes()).hexdigest() == expected_helper
proof = {}
for name in ZT_FILES + ['etc/uci-defaults/96-mango-wifi-led', 'etc/uci-defaults/97-mango-language']:
    dest = support / 'root' / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(old / 'root' / name, dest)
    proof[name] = hashlib.sha256(dest.read_bytes()).hexdigest()
# Keep the independent ZeroTier gateway defaults, without Mango proxy startup.
defaults = (old/'root/etc/uci-defaults/95-mango-proxy').read_text()
defaults = defaults[:defaults.index('/etc/init.d/xray stop')]
start = defaults.index("if ! uci -q get firewall.mango_zt ")
end = defaults.index("if ! uci -q get firewall.mango_mark ")
zt_gateway = defaults[start:end]
start = defaults.index("if ! uci -q get firewall.mango_zt_dns ")
zt_gateway += defaults[start:]
write('package/mango-zerotier-support/root/etc/uci-defaults/95-mango-zerotier',
      '#!/bin/sh\n' + zt_gateway + '\nexit 0\n')
write('package/mango-zerotier-support/Makefile', '''include $(TOPDIR)/rules.mk
PKG_NAME:=mango-zerotier-support
PKG_VERSION:=23
PKG_RELEASE:=1
PKG_LICENSE:=MIT
include $(INCLUDE_DIR)/package.mk
define Package/mango-zerotier-support
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Release 23 ZeroTier direct UDP and gateway support
  DEPENDS:=+zerotier +lua +libuci-lua +nftables-json +flock
endef
define Build/Compile
endef
define Package/mango-zerotier-support/install
	$(CP) ./root/* $(1)/
endef
$(eval $(call BuildPackage,mango-zerotier-support))
''')
# Removed only from this trial's isolated source, not from the baseline repository.
shutil.rmtree(old)
shutil.rmtree(ROOT/'package/mango-tcpcheck')
vendor = ROOT/'vendor/helloworld'
vendor.parent.mkdir(exist_ok=True)
subprocess.run(['git','init',str(vendor)], check=True)
subprocess.run(['git','-C',str(vendor),'remote','add','origin','https://github.com/fw876/helloworld.git'],check=True)
subprocess.run(['git','-C',str(vendor),'fetch','--depth','1','origin',SSR_COMMIT],check=True)
subprocess.run(['git','-C',str(vendor),'checkout','--detach','FETCH_HEAD'],check=True)
assert subprocess.check_output(['git','-C',str(vendor),'rev-parse','HEAD'],text=True).strip()==SSR_COMMIT
for name in ['luci-app-ssr-plus','dns2tcp','lua-neturl','microsocks','tcping']:
    shutil.copytree(vendor/name, ROOT/'package'/name, symlinks=True)
# The selected protocols use TCP endpoints; keep TCP/ICMP GUI probes.
# The standalone UDP nping fallback is only useful for the omitted UDP-only cores.
replace('package/luci-app-ssr-plus/Makefile', '+curl +nping', '+curl +luci-compat')
replace('package/luci-app-ssr-plus/Makefile', 'PKG_RELEASE:=3\n', 'PKG_RELEASE:=9\n')
controller = ROOT/'package/luci-app-ssr-plus/luasrc/controller/shadowsocksr.lua'
text=controller.read_text()
udp_fallback = "\t\tif not e.ping then\n\t\t\tlocal udp_cmd = string.format(\"nping --udp -c 1 -p %d %s 2>/dev/null | grep -o 'Avg rtt: [0-9.]*ms' | awk '{print $3}' | sed 's/ms//' | head -1\", port, domain)\n\t\t\tlocal udp_res = luci.sys.exec(udp_cmd)\n\t\t\tif udp_res and udp_res ~= \"\" then\n\t\t\t\tlocal ping_num = tonumber(udp_res)\n\t\t\t\tif ping_num then e.ping = math.floor(ping_num) end\n\t\t\tend\n\t\tend\n"
assert text.count(udp_fallback)==1
text=text.replace(udp_fallback,'').replace('tcping -> ping -> nping(udp)','tcping -> ping')
controller.write_text(text,encoding='utf-8',newline='\n')
# SSR Plus+ needs only ssr-check, a standalone libc TCP/HTTP probe.
# Do not pull the unused SSR protocol's crypto/event libraries into a one-core image.
check = ROOT/'package/shadowsocksr-libev-check'
(check/'src').mkdir(parents=True)
check_source=(vendor/'shadowsocksr-libev/src/server/check.c').read_text()
check_source=check_source.replace('fd = socket(AF_INET, SOCK_STREAM, 0);',
    'if (argc < 3 || strlen(argv[1]) > 253) return 2;\n        fd = socket(AF_INET, SOCK_STREAM, 0);')
check_source=check_source.replace('char http_url[100]', 'char http_url[512]')
(check/'src/check.c').write_text(check_source)
(check/'Makefile').write_text('''include $(TOPDIR)/rules.mk
PKG_NAME:=shadowsocksr-libev-check
PKG_VERSION:=2.5.6
PKG_RELEASE:=1
PKG_LICENSE:=GPL-3.0
include $(INCLUDE_DIR)/package.mk
define Package/shadowsocksr-libev-ssr-check
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Standalone SSR Plus+ TCP and HTTP check
  DEPENDS:=+libc
endef
define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/check.c $(PKG_BUILD_DIR)/
endef
define Build/Compile
	$(TARGET_CC) $(TARGET_CFLAGS) $(TARGET_CPPFLAGS) -o $(PKG_BUILD_DIR)/ssr-check $(PKG_BUILD_DIR)/check.c $(TARGET_LDFLAGS)
endef
define Package/shadowsocksr-libev-ssr-check/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/ssr-check $(1)/usr/bin/
endef
$(eval $(call BuildPackage,shadowsocksr-libev-ssr-check))
''')
# Use the baseline Xray recipe and its reviewed Vision/UDP443 patch, not the vendor core.
init = 'package/luci-app-ssr-plus/root/etc/init.d/shadowsocksr'
replace(init, 'START=95\n', 'START=95\nexport GOMEMLIMIT=48MiB\nexport GOMAXPROCS=1\n')
# Serialize actions without unlinking an active lock; close lock descriptors in daemon children.
replace(init, 'set_lock() {\n\texec 1000>"$LOCK_FILE"\n\tflock -xn 1000\n}\n\nunset_lock() {\n\tflock -u 1000\n\trm -rf "$LOCK_FILE"\n}\n\nunlock() {\n\tfailcount=1\n\twhile [ "$failcount" -le 10 ]; do\n\t\tif [ -f "$LOCK_FILE" ]; then\n\t\t\tlet "failcount++"\n\t\t\tsleep 1s\n\t\t\t[ "$failcount" -ge 10 ] && unset_lock\n\t\telse\n\t\t\tbreak\n\t\tfi\n\tdone\n}\n', 'set_lock() {\n\texec 9>"$LOCK_FILE"\n\tflock -x -w 60 9 || exit 1\n}\n\nunset_lock() {\n\tflock -u 9 2>/dev/null || true\n\texec 9>&-\n}\n\nunlock() {\n\t# Kernel flock releases dead owners; never unlink another process\'s lock inode.\n\t:\n}\n')
replace(init, '"$@" >/dev/null 2>&1 &', '"$@" 9>&- >/dev/null 2>&1 &')
replace(init, '\t\tstart_rules\n', '\t\tstart_rules 9>&-\n')
replace(init, '\t\tstart_switch\n', '\t\tstart_switch 9>&-\n')
replace(init, '\tstart_monitor\n', '\tstart_monitor 9>&-\n')
replace(init, 'nft list ', 'nft -nn list ', count=11)

# On official OpenWrt the dnsmasq configuration lives in /var/etc.
replace(init, '/tmp/etc/dnsmasq.conf.', '/var/etc/dnsmasq.conf.', count=2)
# The upstream fallback computes /tmp/dnsmasq-ssrplus.d; keep it inside the actual conf-dir.
replace(init, 'TMP_DNSMASQ_PATH="\u0024{DNSMASQ_CONF_DIR%*/}/dnsmasq-ssrplus.d"',
              'TMP_DNSMASQ_PATH="\u0024{DNSMASQ_CONF_DIR%/}/ssrplus"')
# Preserve certificate verification with the pinned March core even after June 2026.
gen = 'package/luci-app-ssr-plus/root/usr/share/shadowsocksr/gen_config.lua'
replace(gen, 'if os.date("%Y.%m.%d") < "2026.06.01" then', 'if true then')
replace(gen, '-- 获取 Xray 版本号', '-- 获取 Xray 版本号')
replace(gen, 'port = tonumber(socks_port),',
    'listen = socks_server.mango_expose == "1" and "0.0.0.0" or "127.0.0.1",\n        port = tonumber(socks_port),')
replace(gen, 'udp = true,', "udp = socks_server.mango_expose ~= '1',")
# Resolve netifd's actual device, and accept all dynamic ZeroTier devices without UCI changes.
rules = 'package/luci-app-ssr-plus/root/usr/bin/ssr-rules'
p = ROOT/rules
s = p.read_text()
resolver = '''
ssr_interface_device() {
	case "$1" in
		zt+) printf '%s\\n' 'zt*'; return ;;
	esac
	local device
	device=$(ubus -t 3 call "network.interface.$1" status 2>/dev/null | jsonfilter -e '@.l3_device')
	[ -n "$device" ] || device=$(uci -q get "network.$1.device")
	[ -n "$device" ] || device=$(uci -P /var/state -q get "network.$1.ifname")
	[ -n "$device" ] && printf '%s\\n' "$device"
}
'''
s = s.replace('\n', '\n'+resolver, 1)
needle = '$(uci -P /var/state get network."$name".ifname 2>/dev/null)'
assert s.count(needle) >= 4
s = s.replace(needle, '$(ssr_interface_device "$name")')
# Numeric dumps avoid blocking early boot on service/name lookups before the DNS relay starts.
assert s.count('NFT="nft"')==1
s=s.replace('NFT="nft"','NFT="nft -nn"')
assert s.count('logger -st ssr-rules[$$] -p$1 $2')==1
s=s.replace('logger -st ssr-rules[$$] -p$1 $2','logger -st "ssr-rules[$$]" -p "$1" -- "$2"')

p.write_text(s,encoding='utf-8',newline='\n')
# Direct all ZeroTier destinations around the transparent proxy, including public ZT ranges.
replace(init, '-b "$(uci_get_by_type access_control wan_bp_ips)"',
        '-b "$(uci_get_by_type access_control wan_bp_ips) $(ip -4 route show table main | awk \'$0 ~ / dev zt/ && $1 != "default" && $1 != "0.0.0.0/0" {print $1}\')"')
# Install the explicitly reviewed migration rather than upstream's destructive first-boot edits.
shutil.copy2(RECIPE/'migration.lua', support/'root/usr/lib/mango/ssr-migration.lua')
for relative, source in [
    ('usr/libexec/ssrplus-migrate','migrate-run.lua'),
    ('etc/uci-defaults/99-ssrplus-migrate','migrate-defaults.sh'),
    ('etc/init.d/ssrplus-direct-socks','direct-socks.sh'),
]:
    dest=support/'root'/relative
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(RECIPE/source,dest)
    dest.chmod(0o755)
ssrroot = ROOT/'package/luci-app-ssr-plus/root'
(ssrroot/'etc/uci-defaults/luci-ssr-plus').write_text('#!/bin/sh\n# Defaults and owner migration handled atomically by 99-ssrplus-migrate.\nexit 0\n')
# Baseline UCI remains in sysupgrade archives even though the old interface is removed.
write('package/mango-zerotier-support/root/lib/upgrade/keep.d/ssrplus-migration',
      '/etc/config/mango_proxy\n/etc/mango-rules/\n/etc/ssrplus/mango-migration/\n')
# Fix helper permissions independently from whether Git preserves a source mode.
for base in [support/'root',ssrroot]:
    for path in base.rglob('*'):
        if path.is_file() and path.read_bytes().startswith(b'#!'):
            path.chmod(0o755)
# Fresh install defaults: proxy disabled, one Xray, no extra server or shunt.
shutil.copy2(RECIPE/'shadowsocksr.config', ssrroot/'etc/config/shadowsocksr')
config = (ROOT/'config/mt300n-v2.config').read_text()
config = '\n'.join(line for line in config.splitlines() if not any(x in line for x in [
    'CONFIG_PACKAGE_luci-app-mango-proxy=', 'CONFIG_PACKAGE_xray-core='])) + '\n'
# Explicit choices are essential: MIPS defaults otherwise omit Xray.
config += '''CONFIG_PACKAGE_xray-core=y
CONFIG_PACKAGE_luci-app-ssr-plus=y
CONFIG_PACKAGE_luci-compat=y
CONFIG_PACKAGE_mango-zerotier-support=y
# CONFIG_PACKAGE_dnsmasq is not set
CONFIG_PACKAGE_dnsmasq-full=y
CONFIG_PACKAGE_dnsmasq_full_nftset=y
# CONFIG_PACKAGE_dnsmasq_full_dnssec is not set
# CONFIG_PACKAGE_dnsmasq_full_auth is not set
# CONFIG_PACKAGE_dnsmasq_full_conntrack is not set
CONFIG_PACKAGE_luci-app-ssr-plus_Nftables_Transparent_Proxy=y
# CONFIG_PACKAGE_luci-app-ssr-plus_Iptables_Transparent_Proxy is not set
CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Xray=y
CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Shadowsocks_NONE_Client=y
CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Shadowsocks_NONE_Server=y
CONFIG_PACKAGE_luci-i18n-ssr-plus-zh-cn=y
'''
optional = ['NONE_V2RAY','V2ray','ChinaDNS_NG','DNS2SOCKS','DNS2SOCKS_RUST','DNSPROXY',
'MosDNS','Hysteria','Tuic_Client','Shadow_TLS','IPT2Socks','Kcptun','NaiveProxy',
'Redsocks2','Shadowsocks_Libev_Client','Shadowsocks_Rust_Client','Shadowsocks_Libev_Server',
'Shadowsocks_Rust_Server','Shadowsocks_Simple_Obfs','Shadowsocks_V2ray_Plugin',
'ShadowsocksR_Libev_Client','ShadowsocksR_Libev_Server','Trojan']
config += ''.join('# CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_'+x+' is not set\n' for x in optional)
write('config/mt300n-v2.config',config)
prepare=(ROOT/'scripts/prepare.sh').read_text()
prepare=prepare.replace('python3 scripts/cn_rules.py\n','')
start=prepare.index('cp -R "$kit/package/luci-app-zerotier-mini"')
end=prepare.index('cp -R "$kit/files" .',start)
prepare=prepare[:start]+'''for pkg in luci-app-zerotier-mini mango-zerotier-support luci-app-ssr-plus dns2tcp lua-neturl microsocks tcping shadowsocksr-libev-check; do
    cp -R "$kit/package/$pkg" package/
done
'''+prepare[end:]
prepare=prepare.replace('chmod +x package/luci-app-mango-proxy/root/etc/hotplug.d/iface/96-mango-zt-direct',
                        'chmod +x package/mango-zerotier-support/root/etc/hotplug.d/iface/96-mango-zt-direct')
prepare=prepare.replace('xray-core luci-app-mango-proxy zerotier','xray-core luci-app-ssr-plus mango-zerotier-support dnsmasq-full zerotier')
prepare=prepare.replace('coreutils-base64 flock mango-tcpcheck','coreutils-base64')
prepare += '''
! grep -qx 'CONFIG_PACKAGE_dnsmasq=y' .config
grep -qx 'CONFIG_PACKAGE_dnsmasq_full_nftset=y' .config
! grep -qx 'CONFIG_PACKAGE_luci-app-mango-proxy=y' .config
for core in v2ray-core sing-box mihomo hysteria tuic-client shadowsocks-rust-sslocal shadowsocks-libev-ss-local shadowsocksr-libev-ssr-local trojan naiveproxy; do
    ! grep -qx "CONFIG_PACKAGE_\u0024{core}=y" .config
done
'''
write('scripts/prepare.sh',prepare)
for path in (ROOT/'tests').glob('*'):
    if not path.is_file(): continue
    s=path.read_text().replace('package/luci-app-mango-proxy/root','package/mango-zerotier-support/root')
    path.write_text(s,encoding='utf-8',newline='\n')
subprocess.run([sys.executable,str(RECIPE/'fix-dns-runtime.py'),str(ROOT)],check=True)
subprocess.run([sys.executable,str(RECIPE/'fix-probe-load.py'),str(ROOT)],check=True)
write('files/etc/mango-build-variant','23-ssrplus-trial\n')
(ROOT/'reports').mkdir(exist_ok=True)
(ROOT/'reports/trial-source.json').write_text(json.dumps({
    'baseline':'Release 23', 'ssr_commit':SSR_COMMIT,'zerotier_source_hashes':proof,
    'helper_sha256':expected_helper,'publish':False,'flash':False,
    'configuration_migration':'generated and fixture-tested; hardware acceptance pending'
},indent=2)+'\n')
print(json.dumps({'trial':'23-ssrplus','ssr_commit':SSR_COMMIT,'zerotier_helpers':len(proof)}))
