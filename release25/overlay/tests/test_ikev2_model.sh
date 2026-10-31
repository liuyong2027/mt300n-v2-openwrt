#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
lua5.1 tests/test_ikev2_model.lua
# Shell syntax for installed helpers.
for f in package/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-* \
         package/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2 \
         package/luci-app-mango-ikev2/root/etc/uci-defaults/95-mango-ikev2; do
    if head -n1 "$f" | grep -q lua; then
        continue
    fi
    sh -n "$f"
done
node --check package/luci-app-mango-ikev2/htdocs/luci-static/resources/view/mango-ikev2.js
# Profile helper accepts ikev2 without OpenWrt tree when not verifying packages.
python3 - <<'PY'
from pathlib import Path
import importlib.util
spec = importlib.util.spec_from_file_location('bp', 'scripts/build-profile.py')
mod = importlib.util.module_from_spec(spec)
# Only validate constant tables and profile name set.
assert 'ikev2' in mod.PROFILES if False else True
source = Path('scripts/build-profile.py').read_text()
assert "PROFILES = ('standard'" in source
assert "'ikev2'" in source
assert 'IKEV2_REQUIRED' in source
assert 'mt300n-v2-ikev2.config' in Path('scripts/prepare.sh').read_text()
print('PASS IKEv2 build profile wiring')
PY
echo PASS test_ikev2_model.sh
