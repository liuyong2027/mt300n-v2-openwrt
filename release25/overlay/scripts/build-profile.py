#!/usr/bin/env python3
"""Build profiles: standard Xray image, optional USB variants, and IKEv2 client image."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

PROFILES = ('standard', 'standard-unpatched', 'r3-usb-baseline', 'r3-usb-patched', 'ikev2')
PATCHED_PROFILES = ('standard', 'r3-usb-patched')
USB_PROFILES = ('r3-usb-baseline', 'r3-usb-patched')
USB_PACKAGES = ('kmod-usb-storage', 'kmod-fs-vfat', 'kmod-fs-exfat', 'block-mount')
IKEV2_REQUIRED = (
    'luci', 'luci-i18n-base-zh-cn', 'luci-i18n-firewall-zh-cn', 'luci-i18n-package-manager-zh-cn',
    'luci-app-mango-ikev2', 'strongswan-minimal', 'strongswan-swanctl',
    'strongswan-mod-eap-mschapv2', 'strongswan-mod-eap-identity', 'strongswan-mod-eap-dynamic',
    'strongswan-mod-openssl', 'kmod-xfrm-interface', 'kmod-ipsec4',
    'zerotier', 'luci-app-zerotier-mini', 'lua', 'libuci-lua', 'ip-full', 'curl',
    'coreutils-base64', 'flock', 'dnsmasq-full'
)
XRAY_REQUIRED = (
    'luci', 'luci-i18n-base-zh-cn', 'luci-i18n-firewall-zh-cn', 'luci-i18n-package-manager-zh-cn',
    'xray-core', 'luci-app-mango-proxy', 'zerotier', 'luci-app-zerotier-mini', 'lua', 'libuci-lua',
    'ip-full', 'curl', 'coreutils-base64', 'flock', 'mango-tcpcheck'
)
FEED_COMMIT = '5caa62e0bc9f7fb9b0c12a23267bceb7724214dd'
MAKEFILE_HASH = 'fa124204193fe4d410a0912a95cd11eda87eca9e02ef5b88cb8b5a63647076dc'
PATCH_NAME = '900-vision-reject-udp443-before-dial.patch'


def configure(kit, tree, profile):
    if profile not in PROFILES:
        raise ValueError('Unknown build profile')
    release = (kit / 'files/etc/mango-release').read_text().strip()
    if not release or '\n' in release:
        raise ValueError('Missing or invalid release marker')
    config = tree / '.config'
    required = []
    patch_hash = None
    if profile == 'ikev2':
        shutil.copyfile(kit / 'config/mt300n-v2-ikev2.config', config)
        required = list(IKEV2_REQUIRED)
    else:
        feed = tree / 'feeds/packages'
        commit = subprocess.check_output(
            ['git', '-C', str(feed), 'rev-parse', 'HEAD'], text=True).strip()
        package = feed / 'net/xray-core'
        makefile = package / 'Makefile'
        original = makefile.read_bytes().replace(b'\r\n', b'\n')
        if commit != FEED_COMMIT or hashlib.sha256(original).hexdigest() != MAKEFILE_HASH:
            raise ValueError('Xray feed/recipe differs from reviewed baseline; refusing R3 build')
        patches = package / 'patches'
        if patches.exists() and any(patches.iterdir()):
            raise ValueError('Unexpected existing Xray patches; review before building')
        if profile in PATCHED_PROFILES:
            candidate = (kit / 'patches/xray-core' / PATCH_NAME).read_bytes()
            patch_hash = hashlib.sha256(candidate).hexdigest()
            patches.mkdir(exist_ok=True)
            (patches / PATCH_NAME).write_bytes(candidate)
            recipe = original.decode().replace('PKG_RELEASE:=1\n', 'PKG_RELEASE:=2\n')
            recipe = recipe.replace('core.build=OpenWrt \\', 'core.build=OpenWrt-Mango-R3EarlyReject \\')
            makefile.write_text(recipe, encoding='utf-8', newline='\n')
        if profile in USB_PROFILES:
            required = list(USB_PACKAGES)
            additions = ''.join(f'CONFIG_PACKAGE_{name}=y\n' for name in required)
            config.write_text(config.read_text() + '\n' + additions, encoding='utf-8', newline='\n')
        required = list(XRAY_REQUIRED) + required
    report = {
        'profile': profile,
        'usb_required_packages': required if profile in USB_PROFILES else [],
        'required_packages': required,
        'release': release,
        'xray_early_reject_enabled': profile in PATCHED_PROFILES,
        'ikev2_client_image': profile == 'ikev2',
        'patch_sha256': patch_hash,
        'hardware_validated': False,
    }
    (kit / 'reports').mkdir(exist_ok=True)
    (kit / 'reports/build-profile.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')
    marker = tree / 'files/etc/mango-build-profile'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(profile + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=PROFILES)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    kit = Path(__file__).resolve().parents[1]
    tree = kit / 'openwrt'
    if args.verify:
        lines = set((tree / '.config').read_text().splitlines())
        required = IKEV2_REQUIRED if args.profile == 'ikev2' else XRAY_REQUIRED
        missing = [name for name in required if f'CONFIG_PACKAGE_{name}=y' not in lines]
        if args.profile in USB_PROFILES:
            missing += [name for name in USB_PACKAGES if f'CONFIG_PACKAGE_{name}=y' not in lines]
        if missing:
            raise SystemExit(f'Required packages dropped by Kconfig: {missing}')
        if args.profile == 'ikev2':
            for banned in ('xray-core', 'luci-app-mango-proxy'):
                if f'CONFIG_PACKAGE_{banned}=y' in lines:
                    raise SystemExit(f'IKEv2 profile must not include {banned}')
    else:
        print(json.dumps(configure(kit, tree, args.profile), indent=2))


if __name__ == '__main__':
    main()
