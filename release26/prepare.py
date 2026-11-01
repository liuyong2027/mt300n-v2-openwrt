#!/usr/bin/env python3
"""Release 26 keeps the Release 25 IKEv2 tree and stamps mango-release 26."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(dest):
    spec = importlib.util.spec_from_file_location('release25_base', ROOT / 'release25' / 'prepare.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    baseline.prepare(dest)
    (dest / 'files' / 'etc' / 'mango-release').write_bytes(b'26\n')
    notes = (ROOT / 'release26' / 'RELEASE-26.md').read_bytes()
    (dest / 'RELEASE-26.md').write_bytes(notes)
    (dest / 'README.md').write_bytes(notes)
    text = (dest / 'files' / 'etc' / 'mango-release').read_text().strip()
    assert text == '26', text
    init = (dest / 'package/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2').read_text()
    assert 'mango_ikev2_claim_charon' in init


if __name__ == '__main__':
    prepare(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'source26'))
