#!/usr/bin/env python3
"""Build the pinned source components; never collect settings from a router."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FEATURE = ROOT / 'tr3600/webfiles'
LOCK = json.loads((FEATURE / 'build-lock.json').read_text())
QUANTUM = ROOT / 'vendor/quantum'
OUT = ROOT / 'tr3600/cudy-webfiles/build-output'
OUT.mkdir(parents=True, exist_ok=True)
(ROOT / 'reports').mkdir(exist_ok=True)

def run(args, cwd, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)

def output(args, cwd):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def arm64(path):
    data = path.read_bytes()
    assert data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == 183

assert output(['git', 'rev-parse', 'HEAD'], QUANTUM) == LOCK['quantum_commit']
assert digest(FEATURE / 'Quantum-jti-fix.patch') == LOCK['quantum_patch_sha256']
assert output(['go', 'version'], ROOT).startswith('go version go' + LOCK['go_version'] + ' ')
assert output(['node', '--version'], ROOT) == 'v' + LOCK['node_version']
run(['git', 'apply', '--check', str(FEATURE / 'Quantum-jti-fix.patch')], QUANTUM)
run(['git', 'apply', str(FEATURE / 'Quantum-jti-fix.patch')], QUANTUM)
frontend = QUANTUM / 'frontend'
frontend_inputs = {name: digest(frontend / name) for name in ('package.json', 'package-lock.json')}
run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], frontend)
run(['npm', 'run', 'build'], frontend)
assert frontend_inputs == {name: digest(frontend / name) for name in frontend_inputs}
assert (QUANTUM / 'backend/internal/web/embed/public/index.html').is_file() or (QUANTUM / 'backend/internal/web/embed/index.html').is_file()
env = dict(os.environ, CGO_ENABLED='0', GOTOOLCHAIN='local')
run(['go', 'test', '-count=1', './...'], FEATURE / 'helper', env)
run(['go', 'test', './internal/auth', '-run', 'TestCudyUniqueJWTForConcurrentUsers', '-count=1'], QUANTUM / 'backend', env)
target = dict(env, GOOS='linux', GOARCH='arm64')
run(['go', 'vet', './...'], FEATURE / 'helper', target)
flags = '-s -w -X github.com/gtsteffaniak/filebrowser/backend/internal/version.Version=' + LOCK['quantum_version'] + ' -X github.com/gtsteffaniak/filebrowser/backend/internal/version.CommitSHA=a29573e-cudy-jti1'
run(['go', 'build', '-trimpath', '-ldflags', flags, '-o', str(OUT / 'filebrowser'), '.'], QUANTUM / 'backend', target)
quantum_hash = digest(OUT / 'filebrowser')
helper_flags = '-s -w -X main.quantumHash=' + quantum_hash
run(['go', 'build', '-trimpath', '-ldflags', helper_flags, '-o', str(OUT / 'cudy-webfiles'), '.'], FEATURE / 'helper', target)
for name in ('cudy-webfiles', 'filebrowser'):
    arm64(OUT / name)
# Execute the same embedded hash and ELF guard used during service startup.
# Comparing binaries with a separate manifest alone missed the rc1 defect.
run(['qemu-aarch64-static', str(OUT / 'cudy-webfiles'), 'verify-binary', str(OUT / 'filebrowser')], ROOT)
manifest = json.loads((FEATURE / 'manifest-template.json').read_text())
manifest['helperSHA256'] = digest(OUT / 'cudy-webfiles')
manifest['quantum']['sha256'] = quantum_hash
(OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
report = {'source_commit': os.environ.get('GITHUB_SHA'), 'lock': LOCK, 'helper_sha256': manifest['helperSHA256'], 'quantum_sha256': manifest['quantum']['sha256'], 'helper_bound_quantum_sha256': quantum_hash, 'actual_ARM64_embedded_binary_guard': 'passed', 'host_helper_tests': 'passed', 'host_quantum_unique_jti_regression': 'passed', 'ARM64_helper_vet': 'passed', 'ELF_ARM64': 'passed', 'frontend_locked_inputs': frontend_inputs, 'new_image_hardware_acceptance': 'not-performed'}
(ROOT / 'reports/webfiles-build.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
