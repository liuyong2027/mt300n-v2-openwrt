#!/usr/bin/env python3
"""Prepare immutable source, evidence and checksum assets after image gates."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
from asset_names import version_image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'tr3600-assets'
VERSION = '1.1.1'
version_image(ASSETS, VERSION)
commit = os.environ['GITHUB_SHA']
proof = json.loads((ASSETS / 'tr3600-verification.json').read_text())
assert proof['source_commit'] == commit
assert proof['version'] == 'tr3600-' + VERSION
assert proof['webfiles_and_DDNS']['clean_image_private_data_absent']
assert proof['webfiles_and_DDNS']['actual_ARM64_embedded_binary_guard'] == 'passed'
assert proof['webfiles_and_DDNS']['upgrade_storage_permission_restoration_case_count'] == 11
assert proof['webfiles_and_DDNS']['upgrade_storage_initializer_before_enable_and_reset'] is True
assert proof['webfiles_and_DDNS']['accepted_hotfix_binary_byte_identical'] is True
assert proof['webfiles_and_DDNS']['actual_packed_boot_startup_diagnostic'] == 'passed'
assert proof['webfiles_and_DDNS']['certificate_validity_days'] == 365
assert proof['webfiles_and_DDNS']['certificate_names_formal'] is True
assert proof['webfiles_and_DDNS']['DDNS_HTTPS_regressions_passed'] is True
assert proof['webfiles_and_DDNS']['boot_readiness_ARM64_tests_passed'] == 46
image = ASSETS / proof['image']
assert hashlib.sha256(image.read_bytes()).hexdigest() == proof['image_sha256']
assert '1.0.0 image has not' not in proof['hardware_validation']
subprocess.run(['git', 'archive', '--format=zip', '--output=' + str(ASSETS / ('SOURCE-' + VERSION + '.zip')), commit], cwd=ROOT, check=True)
quantum = ROOT / 'vendor/quantum'
def filter_source(info):
    parts = Path(info.name).parts
    if any(p in ('.git', 'node_modules') for p in parts):
        return None
    return info
with tarfile.open(ASSETS / ('QUANTUM-SOURCE-' + VERSION + '.tar.gz'), 'w:gz') as archive:
    archive.add(quantum, arcname='quantum-v2.0.0-stable-cudy-jti1', filter=filter_source)
build = json.loads((ASSETS / 'webfiles-build.json').read_text())
provenance = {'firmware_version': proof['version'], 'repository': os.environ['GITHUB_REPOSITORY'], 'source_commit': commit, 'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'TR3600_baseline_commit': 'e298f2b015bc70eac46e0de58204616046cb119f', 'OpenWrt_commit': build['lock']['openwrt_commit'], 'Quantum_commit': build['lock']['quantum_commit'], 'Quantum_patch_sha256': build['lock']['quantum_patch_sha256'], 'Go_version': build['lock']['go_version'], 'Node_version': build['lock']['node_version'], 'new_image_hardware_acceptance': 'pending; not flashed by this build or publication', 'PPTP_included': False}
(ASSETS / ('SOURCE-PROVENANCE-' + VERSION + '.json')).write_text(json.dumps(provenance, indent=2) + '\n')
(ASSETS / 'COMPONENT-ACCEPTANCE.json').write_bytes((ROOT / 'release/tr3600-1.1.1/COMPONENT-ACCEPTANCE.json').read_bytes())
notes = (ROOT / 'tr3600/RELEASE-NOTES.txt').read_text()
(ASSETS / ('RELEASE-' + VERSION + '.txt')).write_text(notes)
files = sorted(p for p in ASSETS.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
(ASSETS / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in files))
print(json.dumps({'source_commit': commit, 'assets': {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files}, 'hardware_acceptance': 'pending'}, indent=2))
