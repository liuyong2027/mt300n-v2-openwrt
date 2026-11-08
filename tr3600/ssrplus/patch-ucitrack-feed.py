#!/usr/bin/env python3
"""Accept the v25.12.6 LuCI feed when the ucitrack init bytes are unchanged."""
from pathlib import Path
import sys

OLD_DECL = "FEED_COMMIT = '128a7812f4be233c5dd7f7466f534fd888785caf'\n"
NEW_DECL = """FEED_COMMIT = '128a7812f4be233c5dd7f7466f534fd888785caf'
# v25.12.6 luci 75a306df84a0 has the same ucitrack init bytes as v25.12.5.
REVIEWED_FEED_COMMITS = {
    '128a7812f4be233c5dd7f7466f534fd888785caf',
    '75a306df84a020c57a631ef5b4c02ace56d93387',
}
"""
OLD_CHECK = (
    "    if commit != FEED_COMMIT:\n"
    "        raise ValueError('LuCI feed commit differs from reviewed baseline; refusing modification')\n"
)
NEW_CHECK = (
    "    if commit not in REVIEWED_FEED_COMMITS:\n"
    "        raise ValueError('LuCI feed commit differs from reviewed baseline; refusing modification')\n"
)

def patch_text(source):
    if 'REVIEWED_FEED_COMMITS' in source:
        raise ValueError('optimize-ucitrack.py feed allowlist already present')
    if source.count(OLD_DECL) != 1 or source.count(OLD_CHECK) != 1:
        raise ValueError('Unexpected optimize-ucitrack.py baseline')
    return source.replace(OLD_DECL, NEW_DECL, 1).replace(OLD_CHECK, NEW_CHECK, 1)

def patch(path):
    path = Path(path)
    path.write_text(patch_text(path.read_text(encoding='utf-8')), encoding='utf-8', newline='\n')

if __name__ == '__main__':
    patch(sys.argv[1])
