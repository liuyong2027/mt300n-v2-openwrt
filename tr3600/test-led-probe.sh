#!/bin/sh
set -eu
task_dir=$(mktemp -d /tmp/cudy-led-probe.XXXXXX)
trap 'rm -rf "$task_dir"' EXIT
mkdir -p "$task_dir/package/luci-app-mango-proxy/root/usr/libexec" "$task_dir/bin"
python3 - "$task_dir" <<'PY'
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys
import shutil
module=SourceFileLoader('led_integration','tr3600/led-integration.py').load_module()
original=Path('package/luci-app-mango-proxy/root/usr/libexec/mango-probe').read_text()
patched=module.patch_probe(original).replace('/usr/libexec/cudy-led-control',sys.argv[1]+'/bin/control')
assert shutil.which('timeout'), 'GNU timeout is required for this host regression'
patched=patched.replace('/usr/libexec/timeout-coreutils',shutil.which('timeout'))
Path(sys.argv[1]+'/package/luci-app-mango-proxy/root/usr/libexec/mango-probe').write_text(patched)
PY
cat > "$task_dir/bin/control" <<'SH'
#!/bin/sh
# An unavailable LED backend must never turn a successful proxy probe into failure.
exit 1
SH
chmod +x "$task_dir/bin/control"
sh tests/test_probe_logging.sh "$task_dir"
cat > "$task_dir/bin/control" <<'SH'
#!/bin/sh
printf '%s\n' "$1" >> "$CUDY_TEST_LED_CALLS"
case "$1" in begin) printf '%s' '{"id":"fixture-only"}';; finish) exit 0;; *) exit 1;; esac
SH
export CUDY_TEST_LED_CALLS="$task_dir/observations"
sh tests/test_probe_logging.sh "$task_dir"
grep -q '^begin$' "$task_dir/observations"
grep -q '^finish$' "$task_dir/observations"
# Actual timeout semantics are verified independently of networking.
if timeout 1 sh -c 'sleep 5'; then echo 'Timeout did not bound the helper' >&2; exit 1; fi
echo 'LED best-effort observations preserve all existing proxy result/logging cases'
