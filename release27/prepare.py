#!/usr/bin/env python3
"""Rebuild the pinned Release 26 recipe, then apply reviewed Release 27 fixes."""
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = '588ed68c02d8bbdaa0db19af106b91d9ec15c508'


def prepare(dest):
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit('Destination must be empty; use a fresh source directory')
    spec = importlib.util.spec_from_file_location('release26_base', ROOT / 'release26/prepare.py')
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.prepare(dest)
    before = {p.relative_to(dest).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in dest.rglob('*') if p.is_file()}
    for p in sorted((ROOT / 'release27/overlay').rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts:
            continue
        target = dest / p.relative_to(ROOT / 'release27/overlay')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
        target.chmod(0o755 if p.read_bytes().startswith(b'#!') else 0o644)
    (dest / 'files/etc/mango-release').write_text('27\n')
    notes = (ROOT / 'release27/RELEASE-27.md').read_bytes()
    (dest / 'README.md').write_bytes(notes)
    (dest / 'RELEASE-27.md').write_bytes(notes)
    hashes = {p.relative_to(dest).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in dest.rglob('*') if p.is_file()
              and p.name not in ('SOURCE-FILES-SHA256SUMS', 'SOURCE-DELTA-27.json')}
    delta = dict(version='27', base_commit=BASE_COMMIT,
                 integrated_hotfix='67f556ab404c5ee7b31d771ff5396f5840ff60da',
                 issues=[9], hardware_acceptance='pending',
                 changed_files={k: v for k, v in hashes.items() if before.get(k) != v})
    (dest / 'SOURCE-DELTA-27.json').write_text(json.dumps(delta, indent=2) + '\n')
    hashes['SOURCE-DELTA-27.json'] = hashlib.sha256((dest / 'SOURCE-DELTA-27.json').read_bytes()).hexdigest()
    (dest / 'SOURCE-FILES-SHA256SUMS').write_text(''.join(h + '  ' + p + '\n' for p, h in sorted(hashes.items())))
    print(json.dumps(delta, indent=2))


if __name__ == '__main__':
    prepare(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'source27'))
