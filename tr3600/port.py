#!/usr/bin/env python3
"""Adapt the verified 1f61697 source bundle for Cudy TR3600 v1."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_HASH = '8dc17ef842929725b10a0152569a690c7ffe148473b1005cd7d610cda510e787'

def replace_once(path, old, new):
    s = path.read_text(encoding='utf-8')
    assert s.count(old) == 1, (path, old)
    path.write_text(s.replace(old, new), encoding='utf-8', newline='\n')

def extract():
    data = base64.b64decode((ROOT/'release20-test-failover1-source.zip.b64').read_text().strip(), validate=True)
    assert hashlib.sha256(data).hexdigest() == BUNDLE_HASH
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert len(names) == len(set(names))
        for name in names:
            p = PurePosixPath(name)
            assert not p.is_absolute() and '..' not in p.parts and '\\' not in name
        listed = []
        for row in z.read('SOURCE-FILES-SHA256SUMS').decode().splitlines():
            digest, name = row.split('  ', 1)
            assert hashlib.sha256(z.read(name)).hexdigest() == digest, name
            listed.append(name)
        assert set(listed) == set(names) - {'SOURCE-FILES-SHA256SUMS'}
        z.extractall(ROOT)

def adapt():
    # Keep the same OpenWrt revision, locked feeds, R3 patch and proxy sources.
    prepare = ROOT/'scripts/prepare.sh'
    replace_once(prepare, 'cd openwrt\n', 'cd openwrt\ngit apply --check "$kit/tr3600/support.patch"\ngit apply "$kit/tr3600/support.patch"\ngit apply --check "$kit/tr3600/hardware-fixes.patch"\ngit apply "$kit/tr3600/hardware-fixes.patch"\ncp "$kit/tr3600/999-ubi-add-configurable-rootdev.patch" target/linux/mediatek/patches-6.12/\npython3 "$kit/tr3600/upgrade-integration.py" "$PWD"\npython3 "$kit/tr3600/network-defaults.py" "$PWD"\n')
    replace_once(prepare, '$kit/config/mt300n-v2.config', '$kit/tr3600/tr3600.config')
    replace_once(prepare, 'cp -R "$kit/package/mango-tcpcheck" package/', 'cp -R "$kit/package/mango-tcpcheck" package/\ncp -R "$kit/tr3600/luci-app-cudy-l2tp" package/\ncp -R "$kit/tr3600/cudy-l2tp-ifname" package/\nchmod +x package/luci-app-cudy-l2tp/root/etc/init.d/cudy_l2tp package/luci-app-cudy-l2tp/root/etc/uci-defaults/94-cudy-l2tp package/luci-app-cudy-l2tp/root/usr/libexec/cudy-l2tp-config')
    replace_once(prepare, 'CONFIG_TARGET_ramips_mt76x8_DEVICE_glinet_gl-mt300n-v2=y', 'CONFIG_TARGET_mediatek_filogic_DEVICE_cudy_tr3600-v1=y')
    # Preserve LAN 192.168.8.1. Leave wireless disabled until the owner configures
    # country/password in LuCI; do not copy the Mango's open 2.4 GHz AP defaults.
    network = ROOT/'files/etc/board.d/99-mango-network'
    network.write_text('''#!/bin/sh
. /lib/functions/uci-defaults.sh
[ "$(board_name)" = 'cudy,tr3600-v1' ] || exit 0
board_config_update
ucidef_set_interface lan protocol static ipaddr '192.168.8.1' netmask '255.255.255.0'
board_config_flush
exit 0
''', encoding='utf-8', newline='\n')
    runtime = ROOT/'scripts/validate-runtime.sh'
    replace_once(runtime, 'if [ "${1:-}" = mips ]; then', 'if [ "${1:-}" = arm64 ]; then')
    replace_once(runtime, 'root-ramips', 'root-mediatek')
    s = runtime.read_text().replace('qemu-mipsel-static', 'qemu-aarch64-static').replace('actual_mips_xray', 'actual_arm64_xray').replace('MIPS', 'ARM64')
    runtime.write_text(s, encoding='utf-8', newline='\n')
    (ROOT/'files/etc/mango-device').write_text('cudy,tr3600-v1\n')
    (ROOT/'files/etc/mango-kernel-profile').write_text('openwrt-filogic-default\n')
    shutil.copyfile(ROOT/'tr3600/cudy-upgrade.sh', ROOT/'files/lib-upgrade-cudy.tmp')
    destination = ROOT/'files/lib/upgrade/cudy-tr3600.sh'
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(ROOT/'files/lib-upgrade-cudy.tmp', destination)
    network_root = ROOT/'tr3600/network-root'
    shutil.copytree(network_root, ROOT/'files', dirs_exist_ok=True)
    (ROOT/'files/etc/hotplug.d/iface/95-cudy-tr3600-eee').chmod(0o755)
    (ROOT/'files/etc/fw_env.config').write_text('/dev/ubi0_0 0 0x80000 0x80000 1\n')
    provenance = {'application_commit': '1f6169759396a31d2e3beec35d300c1fe4f2eaec',
                  'original_bundle_sha256': BUNDLE_HASH,
                  'openwrt_commit': 'f0a60eee2fe051741c643ea6118718aae1ef17fb',
                  'device_patch_commit': '046aec0dccd90f5a156cb8e9725c121c81955dd3',
                  'device': 'cudy,tr3600-v1', 'kernel_profile': 'OpenWrt Filogic defaults',
                  'requested_features': ['USB file sharing (Samba4)', 'Wi-Fi client/AP repeater', 'IPv4 relayd pseudo bridge', 'L2TP/IPsec VPN server (disabled until configured)'],
                  'hardware_validation': 'pending', 'wireless_first_boot': 'disabled; configure country and password in LuCI'}
    (ROOT/'reports').mkdir(exist_ok=True)
    (ROOT/'reports/tr3600-source.json').write_text(json.dumps(provenance, indent=2)+'\n')

if __name__ == '__main__':
    extract()
    adapt()
