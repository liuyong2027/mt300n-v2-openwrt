#!/usr/bin/env python3
"""Verify the image container, extracted filesystem, architecture and metadata."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
from importlib.machinery import SourceFileLoader
led_integration = SourceFileLoader("led_integration", str(Path(__file__).parent/"led-integration.py")).load_module()
usb_integration = SourceFileLoader("usb_integration", str(Path(__file__).parent/"usb-integration.py")).load_module()

kit = Path(__file__).resolve().parents[1]
tree = kit/'openwrt'
reports = kit/'reports'
assets = kit/'tr3600-assets'
assets.mkdir(exist_ok=False)
config = (tree/'.config').read_text().splitlines()
for name in ('TARGET_mediatek_filogic_DEVICE_cudy_tr3600-v1', 'PACKAGE_kmod-mt7990-firmware',
             'PACKAGE_mt7987-2p5g-phy-firmware', 'PACKAGE_kmod-hwmon-pwmfan',
             'PACKAGE_ethtool', 'PACKAGE_luci-app-cudy-wifi', 'PACKAGE_luci-app-cudy-led', 'PACKAGE_luci-app-cudy-usb', 'PACKAGE_usteer', 'PACKAGE_wpad-mbedtls',
             'PACKAGE_luci-lib-nixio', 'PACKAGE_luci-lib-jsonc', 'PACKAGE_coreutils-timeout',
             'PACKAGE_kmod-usb3', 'PACKAGE_uboot-envtools', 'LUCI_JSMIN',
             'PACKAGE_luci-app-samba4', 'PACKAGE_samba4-server',
             'PACKAGE_block-mount', 'PACKAGE_kmod-usb-storage',
             'PACKAGE_kmod-usb-storage-uas', 'PACKAGE_kmod-fs-ext4',
             'PACKAGE_kmod-fs-exfat', 'PACKAGE_kmod-fs-vfat',
             'PACKAGE_kmod-fs-ntfs3', 'PACKAGE_luci-proto-relay', 'PACKAGE_relayd'
):
    assert 'CONFIG_'+name+'=y' in config, name
assert 'CONFIG_TARGET_SQUASHFS_BLOCK_SIZE=1024' in config
images = list((tree/'bin/targets/mediatek/filogic').glob('*cudy_tr3600-v1-squashfs-sysupgrade.bin'))
assert len(images) == 1, images
image = images[0]
assert image.stat().st_size < 237824*1024
with tarfile.open(image) as t:
    prefix = 'sysupgrade-cudy_tr3600-v1/'
    kernel = t.extractfile(prefix+'kernel').read()
    root = t.extractfile(prefix+'root').read()
assert kernel[:4] == bytes.fromhex('d00dfeed')
assert root[:4] == b'hsqs'
assert struct.unpack_from('<I', root, 12)[0] == 1048576
assert struct.unpack_from('<H', root, 20)[0] == 4
(reports/'image-root.squashfs').write_bytes(root)
extracted = reports/'extracted-image-rootfs'
# SquashFS includes /dev/console and root-only files: preserve all entries.
subprocess.run(['sudo', str(tree/'staging_dir/host/bin/unsquashfs4'), '-no-progress', '-d', str(extracted), str(reports/'image-root.squashfs')], check=True)
# Keep the recorded modes, while allowing this runner to read private files.
subprocess.run(['sudo', 'chown', '-hR', f'{os.getuid()}:{os.getgid()}', str(extracted)], check=True)
expected = json.loads((kit/'VALIDATION-20.json').read_text())
for name, digest in expected['source_rootfs_sha256'].items():
    if name == 'usr/libexec/mango-probe':
        original = (kit/'package/luci-app-mango-proxy/root'/name).read_bytes()
        assert hashlib.sha256(original).hexdigest() == digest, name
        assert (extracted/name).read_bytes() == led_integration.patch_probe(original.decode()).encode(), name
    else:
        assert hashlib.sha256((extracted/name).read_bytes()).hexdigest() == digest, name
assert (extracted/'etc/mango-release').read_text().strip() == '20-test-failover1'
assert (extracted/'etc/mango-device').read_text().strip() == 'cudy,tr3600-v1'
assert (extracted/'lib/upgrade/cudy-tr3600.sh').read_bytes() == (kit/'tr3600/cudy-upgrade.sh').read_bytes()
def arm64(p):
    b = p.read_bytes()
    assert b[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', b, 18)[0] == 183, p
for name in ('usr/bin/xray', 'bin/busybox', 'usr/libexec/mango-tcpcheck', 'usr/sbin/smbd', 'usr/sbin/relayd'):
    arm64(extracted/name)
network_root = kit/'tr3600/network-root'
for source in network_root.rglob('*'):
    if source.is_file():
        installed = extracted/source.relative_to(network_root)
        assert installed.read_bytes() == source.read_bytes(), source
        if source.read_bytes().startswith(b'#!'):
            assert installed.stat().st_mode & 0o111, installed
arm64(extracted/'usr/sbin/ethtool')
arm64(extracted/'sbin/usteerd')
arm64(extracted/'usr/sbin/wpad')
arm64(extracted/'usr/libexec/timeout-coreutils')
assert 'CONFIG_PACKAGE_wpad-basic-mbedtls=y' not in config
wifi_root = kit/'tr3600/luci-app-cudy-wifi/root'
for source in wifi_root.rglob('*'):
    if source.is_file():
        installed = extracted/source.relative_to(wifi_root)
        assert installed.read_bytes() == source.read_bytes(), source
        if source.read_bytes().startswith(b'#!'):
            assert installed.stat().st_mode & 0o111, installed
wifi_js = kit/'tr3600/luci-app-cudy-wifi/htdocs/luci-static/resources/view/cudy-wifi.js'
wifi_minified = subprocess.run([str(tree/'staging_dir/hostpkg/bin/jsmin')], input=wifi_js.read_bytes(), stdout=subprocess.PIPE, check=True).stdout
assert (extracted/'www/luci-static/resources/view/cudy-wifi.js').read_bytes() == wifi_minified
led_root = kit/'tr3600/luci-app-cudy-led/root'
for source in led_root.rglob('*'):
    if source.is_file():
        installed = extracted/source.relative_to(led_root)
        assert installed.read_bytes() == source.read_bytes(), source
        if source.read_bytes().startswith(b'#!'):
            assert installed.stat().st_mode & 0o111, installed
led_js = kit/'tr3600/luci-app-cudy-led/htdocs/luci-static/resources/view/cudy-led.js'
led_minified = subprocess.run([str(tree/'staging_dir/hostpkg/bin/jsmin')], input=led_js.read_bytes(), stdout=subprocess.PIPE, check=True).stdout
assert (extracted/'www/luci-static/resources/view/cudy-led.js').read_bytes() == led_minified
usb_root = kit/'tr3600/luci-app-cudy-usb/root'
for source in usb_root.rglob('*'):
    if source.is_file():
        installed = extracted/source.relative_to(usb_root)
        assert installed.read_bytes() == source.read_bytes(), source
        if source.read_bytes().startswith(b'#!'):
            assert installed.stat().st_mode & 0o111, installed
usb_js = kit/'tr3600/luci-app-cudy-usb/htdocs/luci-static/resources/view/cudy-usb.js'
usb_minified = subprocess.run([str(tree/'staging_dir/hostpkg/bin/jsmin')], input=usb_js.read_bytes(), stdout=subprocess.PIPE, check=True).stdout
assert (extracted/'www/luci-static/resources/view/cudy-usb.js').read_bytes() == usb_minified
assert (extracted/'etc/init.d/samba4').read_text() == usb_integration.patch_text((kit/'tr3600/fixtures/samba-5caa62e0.init').read_text())
for module in ('catia', 'fruit', 'streams_xattr', 'xattr_tdb'):
    arm64(extracted/('usr/lib/samba/vfs/'+module+'.so'))
assert (extracted/'sbin/sysupgrade').read_bytes() == (tree/'package/base-files/files/sbin/sysupgrade').read_bytes()
assert 'cudy-led-upgrade suspend' in (extracted/'sbin/sysupgrade').read_text()
assert (extracted/'usr/libexec/mango-probe').stat().st_mode & 0o111
wireless_defaults = extracted/'lib/wifi/mac80211.uc'
assert wireless_defaults.read_bytes() == (tree/'package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc').read_bytes()
subprocess.run(['python3', str(kit/'tr3600/check-removed.py'), str(extracted), str(tree/'.config')], check=True)
assert (extracted/'etc/cudy-release').read_text().strip() == 'tr3600-test3'
ui_source = (kit/'package/luci-app-mango-proxy/htdocs/luci-static/resources/view/mango-proxy.js').read_bytes()
assert hashlib.sha256(ui_source).hexdigest() == expected['ui_source_sha256']
ui_expected = subprocess.run([str(tree/'staging_dir/hostpkg/bin/jsmin')], input=ui_source, stdout=subprocess.PIPE, check=True).stdout
assert (extracted/'www/luci-static/resources/view/mango-proxy.js').read_bytes() == ui_expected
runtime = json.loads((reports/'runtime-validation.json').read_text())
assert runtime['actual_arm64_xray'] == 'passed' and runtime['configurations'] > 0
assert runtime['core_sha256'] == hashlib.sha256((extracted/'usr/bin/xray').read_bytes()).hexdigest()
subprocess.run([str(tree/'staging_dir/host/bin/fwtool'), '-i', str(reports/'image-metadata.json'), str(image)], check=True)
metadata = json.loads((reports/'image-metadata.json').read_text())
assert 'cudy,tr3600-v1' in metadata['supported_devices']
assert 'R126' in metadata['supported_devices']
linux = list((tree/'build_dir').glob('target-*/linux-mediatek_filogic/linux-6.12.*'))
assert len(linux) == 1
symbols = (linux[0]/'System.map').read_text()
assert '__param_dual_boot' in symbols and '__param_rootfs_volume' in symbols
shutil.copyfile(linux[0]/'.config', reports/'actual-kernel.config')
proof = {'device': 'cudy,tr3600-v1', 'version': '20-test-failover1-tr3600-test3',
         'image': image.name, 'image_bytes': image.stat().st_size,
         'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
         'container': 'sysupgrade tar with FIT kernel and SquashFS rootfs',
         'squashfs_block_bytes': 1048576, 'squashfs_compression': 'xz',
         'actual_arm64_xray': runtime, 'rootfs_original_hashes': 'passed; original probe source and exact additive LED hook verified',
         'ui_jsmin_comparison': 'passed', 'dual_boot_kernel_parameters': 'present',
         'usb_sharing_and_repeater_packages': 'selected; smbd and relayd ARM64 binaries verified',
         'usb_disk_consent': 'selected; exact LuCI/helpers/menu/ACL, per-share Samba guards and ARM64 metadata VFS modules verified; new disks not shared without consent',
         'status_leds': 'selected; exact Lua/scripts/LuCI/probe hook and upgrade handoff verified; status mode default, night off',
         'unified_wifi': 'selected; full ARM64 wpad/usteer, exact helper/configuration and LuCI page verified; disabled by default',
         'removed_features': 'L2TP/IPsec server and dynamic DNS packages/pages absent; previous owned firewall/configuration cleanup included',
         'hardware_validation': 'new image pending; previous test1 installed and reboot/USB/proxy checked'}
(reports/'tr3600-verification.json').write_text(json.dumps(proof, indent=2)+'\n')
shutil.copyfile(image, assets/image.name)
for source in ('tr3600-source.json', 'tr3600-verification.json', 'image-metadata.json', 'resolved.config', 'feed-commits.txt', 'actual-kernel.config'):
    shutil.copyfile(reports/source, assets/source)
shutil.copyfile(kit/'tr3600/README.txt', assets/'README.txt')
(assets/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(assets.iterdir()) if p.is_file()))
print(json.dumps(proof, indent=2))
