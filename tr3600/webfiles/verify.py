#!/usr/bin/env python3
"""Verify the new components in the packed image, in addition to TR1 gates."""
import hashlib
import json
from pathlib import Path
import stat
import struct
import subprocess

def verify(image_root, kit):
    root, kit = Path(image_root), Path(kit)
    config = set((kit / 'openwrt/.config').read_text().splitlines())
    required = ('cudy-webfiles', 'luci-app-cudy-webfiles', 'ddns-scripts', 'ddns-scripts-services', 'luci-app-ddns', 'luci-i18n-ddns-zh-cn', 'resolveip')
    for name in required:
        assert 'CONFIG_PACKAGE_' + name + '=y' in config, name
    core = kit / 'tr3600/cudy-webfiles'
    ui = kit / 'tr3600/luci-app-cudy-webfiles'
    for package in (core, ui):
        for source in (package / 'root').rglob('*'):
            if source.is_file():
                installed = root / source.relative_to(package / 'root')
                assert installed.read_bytes() == source.read_bytes(), source
                if source.read_bytes().startswith(b'#!'):
                    assert installed.stat().st_mode & 0o111, installed
    manifest = json.loads((root / 'usr/lib/cudy-webfiles/manifest.json').read_text())
    expected_manifest = json.loads((core / 'build-output/manifest.json').read_text())
    assert manifest == expected_manifest
    for name, expected in (('cudy-webfiles', manifest['helperSHA256']), ('filebrowser', manifest['quantum']['sha256'])):
        path = root / 'usr/lib/cudy-webfiles/bin' / name
        data = path.read_bytes()
        assert data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == 183, name
        assert hashlib.sha256(data).hexdigest() == expected, name
        assert path.stat().st_mode & 0o111
    binary_dir = root / 'usr/lib/cudy-webfiles/bin'
    subprocess.run(['qemu-aarch64-static', str(binary_dir / 'cudy-webfiles'), 'verify-binary', str(binary_dir / 'filebrowser')], check=True)
    js = ui / 'htdocs/luci-static/resources/view/cudy-webfiles.js'
    transformed = subprocess.run([str(kit / 'openwrt/staging_dir/hostpkg/bin/jsmin')], input=js.read_bytes(), stdout=subprocess.PIPE, check=True).stdout
    assert (root / 'www/luci-static/resources/view/cudy-webfiles.js').read_bytes() == transformed
    defaults = (root / 'etc/config/cudy_webfiles').read_text()
    for line in ("option enabled '0'", "option volume ''", "option port '8080'", "option read_write '0'", "option zerotier '0'", "option public_enabled '0'"):
        assert line in defaults, line
    assert 'START=99' in (root / 'etc/init.d/cudy-webfiles').read_text()
    assert 'START=97' in (root / 'etc/init.d/cudy_usb').read_text()
    keep = (root / 'lib/upgrade/keep.d/cudy-webfiles').read_text().splitlines()
    assert '/etc/config/cudy_webfiles' in keep and '/etc/cudy-webfiles/' in keep
    assert not (root / 'etc/cudy-webfiles').exists(), 'Generated account keys, accounts and TLS must not be published in a clean image'
    assert (root / 'etc/init.d/ddns').is_file()
    assert (root / 'etc/config/ddns').is_file()
    provider_files = []
    for base in ('usr/share/ddns', 'usr/lib/ddns'):
        provider_files += list((root / base).rglob('*dynu*'))
    assert any(p.is_file() for p in provider_files), 'Dynu provider data missing'
    retire = (root / 'etc/uci-defaults/91-cudy-retire-services').read_text()
    assert 'for config in cudy_l2tp ddns;' not in retire
    assert 'for service in cudy_l2tp xl2tpd swanctl ddns;' not in retire
    report = {'version': manifest['version'], 'integration_revision': manifest['integrationRevision'], 'package_files_exact': True, 'ARM64_binaries_and_hashes': True, 'jsmin_comparison': True, 'fresh_defaults_disabled_no_personal_volume': True, 'startup_priority': 99, 'persistent_accounts_keys_TLS_keep_list': True, 'clean_image_private_data_absent': True, 'DDNS_and_Dynu_provider_present': True, 'DDNS_legacy_cleanup_retired': True, 'hardware_acceptance': 'pending; no automatic flash'}
    report['actual_ARM64_embedded_binary_guard'] = 'passed'
    (kit / 'reports/webfiles-image-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
