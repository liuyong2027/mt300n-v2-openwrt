#!/usr/bin/env python3
"""Exercise the real ARM64 startup binary guard, including a changed payload."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('helper', type=Path)
parser.add_argument('quantum', type=Path)
parser.add_argument('--unbound-helper', type=Path)
parser.add_argument('--runner', default='qemu-aarch64-static')
parser.add_argument('--report', type=Path)
args = parser.parse_args()

def check(helper, payload, expected_error=None):
    command = ([args.runner] if args.runner else []) + [str(helper.resolve()), 'verify-binary', str(payload.resolve())]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    if expected_error:
        assert result.returncode != 0 and expected_error in result.stderr, (result.returncode, result.stderr)
    else:
        assert result.returncode == 0 and 'VERIFIED:' in result.stdout, (result.returncode, result.stderr)

check(args.helper, args.quantum)
with tempfile.TemporaryDirectory(prefix='cudy-binary-guard-') as directory:
    changed = Path(directory) / 'modified-quantum'
    shutil.copyfile(args.quantum, changed)
    with changed.open('ab') as stream:
        stream.write(b'cudy-disposable-tamper-fixture')
    check(args.helper, changed, 'SHA256 mismatch')
if args.unbound_helper:
    check(args.unbound_helper, args.quantum, 'not bound')
report = {
    'helper_sha256': hashlib.sha256(args.helper.read_bytes()).hexdigest(),
    'quantum_sha256': hashlib.sha256(args.quantum.read_bytes()).hexdigest(),
    'actual_ARM64_embedded_binary_guard': 'passed',
    'tampered_payload_rejected': True,
    'unbound_build_rejected': True if args.unbound_helper else 'not-requested',
    'hardware_service_start_test': 'not-performed-by-this-script',
}
if args.report:
    args.report.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
