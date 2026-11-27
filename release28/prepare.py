#!/usr/bin/env python3
"""Build the Release 28 recipe on top of the Release 27 IKEv2 source."""

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE_COMMIT = '934c0a7f6918d455b959bd2066c0261d59d82c1b'
BASE_MANIFEST = 'SOURCE-DELTA-27.json'
DELTA = 'SOURCE-DELTA-28.json'
CHECKSUMS = 'SOURCE-FILES-SHA256SUMS'


def hashes(dest):
    return {
        path.relative_to(dest).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(dest.rglob('*'))
        if path.is_file() and path.name not in {BASE_MANIFEST, DELTA, CHECKSUMS}
    }


def prepare(dest):
    spec = importlib.util.spec_from_file_location(
        'release27_base', ROOT.parent / 'release27' / 'prepare.py'
    )
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.prepare(dest)
    before = hashes(dest)
    (dest / BASE_MANIFEST).unlink()

    overlay = ROOT / 'overlay'
    for source in sorted(overlay.rglob('*')):
        if not source.is_file() or '__pycache__' in source.parts:
            continue
        target = dest / source.relative_to(overlay)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if source.read_bytes().startswith(b'#!') else 0o644)

    (dest / 'files/etc/mango-release').write_bytes(b'28\n')
    notes = (ROOT / 'RELEASE-28.md').read_bytes()
    (dest / 'README.md').write_bytes(notes)
    (dest / 'RELEASE-28.md').write_bytes(notes)

    files = hashes(dest)
    delta = {
        'version': '28',
        'base_commit': BASE_COMMIT,
        'hardware_acceptance': 'pending',
        'changed_files': {name: sha for name, sha in files.items() if before.get(name) != sha},
    }
    encoded = (json.dumps(delta, indent=2) + '\n').encode('utf-8')
    (dest / DELTA).write_bytes(encoded)
    files[DELTA] = hashlib.sha256(encoded).hexdigest()
    (dest / CHECKSUMS).write_bytes(
        ''.join(f'{sha}  {name}\n' for name, sha in sorted(files.items())).encode('utf-8')
    )
    print(json.dumps(delta, indent=2))


if __name__ == '__main__':
    prepare(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / 'source28')
