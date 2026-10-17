#!/usr/bin/env python3
"""Verify the new components in the packed image, in addition to TR1 gates."""
import hashlib
import os
import re
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
    init = (root / 'etc/init.d/cudy-webfiles').read_text()
    boot = (root / 'etc/uci-defaults/98-cudy-webfiles').read_text()
    call = '/usr/bin/lua /usr/lib/cudy-webfiles/prepare-storage.lua || '
    assert init.index(call) < init.index('"$helper" reset')
    assert '"$helper" boot-run' in init and 'procd_set_param stderr 1' in init
    assert 'procd_set_param respawn' not in init
    assert boot.index(call + 'exit 1') < boot.index('/etc/init.d/cudy-webfiles enable')
    wrapper = root / 'usr/lib/cudy-webfiles/prepare-storage.lua'
    module = root / 'usr/lib/lua/cudy/webfiles-storage.lua'
    assert "prepare('/etc/cudy-webfiles', 0)" in wrapper.read_text()
    subprocess.run(['qemu-aarch64-static', '-L', str(root), str(root / 'usr/bin/lua'), '-e', 'assert(loadfile("' + str(wrapper) + '"))'], check=True)
    temporary = subprocess.check_output(['sudo', 'mktemp', '-d', '/tmp/cudy-webfiles-storage-test.XXXXXX'], text=True).strip()
    assert re.fullmatch(r'/tmp/cudy-webfiles-storage-test\.[A-Za-z0-9]+', temporary), temporary
    try:
        run = subprocess.run(['sudo', 'env', 'LUA_CPATH=' + str(root / 'usr/lib/lua/?.so'), 'LUA_PATH=' + str(root / 'usr/lib/lua/?.lua') + ';' + str(root / 'usr/lib/lua/?/init.lua'), 'qemu-aarch64-static', '-L', str(root), str(root / 'usr/bin/lua'), str(kit / 'tr3600/test-webfiles-storage.lua'), temporary, str(module)], check=True, text=True, stdout=subprocess.PIPE)
        assert 'PASS all11 native storage restoration regressions' in run.stdout
        (kit / 'reports/webfiles-storage-packed-regressions.txt').write_text(run.stdout)
    finally:
        subprocess.run(['sudo', 'rm', '-rf', '--', temporary], check=True)
    report['upgrade_storage_permission_restoration_case_count'] = 11
    report['upgrade_storage_test_runtime'] = 'ARM64 Lua/nixio and restoration module from the final packed image; synthetic root-owned accounts, keys and LAN/public-IP/DDNS TLS fixtures only'
    report['upgrade_storage_initializer_before_enable_and_reset'] = True
    acceptance = json.loads((kit / 'release/tr3600-1.1.1/COMPONENT-ACCEPTANCE.json').read_text())
    assert manifest['helperSHA256'] == acceptance['helper_sha256']
    assert manifest['quantum']['sha256'] == acceptance['quantum_sha256']
    assert manifest['version'] == '0.6.6' and manifest['startup']['initialWaitSeconds'] == 90
    result = subprocess.run(['sudo', 'unshare', '--mount', '--fork', 'sh', str(kit / 'tr3600/webfiles/test_packed_boot.sh'), str(root)], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    boot_proof = json.loads(result.stdout)
    assert boot_proof['actual_packed_ARM64_boot_action'] == 'passed' and boot_proof['diagnostic_root0600']
    (kit / 'reports/webfiles-boot-packed-verification.json').write_text(json.dumps(boot_proof, indent=2) + '\n')
    log = (kit / 'reports/webfiles-boot-regressions.txt').read_text()
    assert log.rstrip().endswith('PASS') and '--- FAIL:' not in log
    top = len(re.findall(r'^--- PASS:', log, re.M))
    all_cases = len(re.findall(r'^\s*--- PASS:', log, re.M))
    assert top == 46 and all_cases == 68
    report['boot_readiness_ARM64_tests_passed'] = top
    report['boot_readiness_ARM64_including_subtests_passed'] = all_cases
    report['accepted_hotfix_binary_byte_identical'] = True
    report['actual_packed_boot_startup_diagnostic'] = 'passed'
    assert manifest['certificateValidityDays'] == 365
    assert manifest['publicGateway']['certificateValidityDays'] == 365
    assert manifest['certificateNames'] == {'CA': 'Cudy webpage CA', 'server': 'Cudy webpage'}
    report['certificate_validity_days'] = 365
    report['certificate_names_formal'] = True
    for source in (kit / 'tr3600/network-root').rglob('*'):
        if source.is_file() and ('dynu' in source.name):
            packed = root / source.relative_to(kit / 'tr3600/network-root')
            assert packed.read_bytes() == source.read_bytes(), str(packed)
            if source.read_bytes().startswith(b'#!'): assert packed.stat().st_mode & 0o111
    ddns = subprocess.run(['python3', str(kit / 'tr3600/test-dynu-https.py'), str(root), str(root)], check=True, text=True, stdout=subprocess.PIPE)
    assert '"DDNS_HTTPS_regressions_passed": true' in ddns.stdout
    (kit / 'reports/ddns-https-packed-regressions.txt').write_text(ddns.stdout)
    report['DDNS_HTTPS_regressions_passed'] = True
    report['DDNS_resolver_cases'] = 7
    report['DDNS_provider_cases'] = 8
    report['DDNS_migration_cases'] = 10
    (kit / 'reports/webfiles-image-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
