#!/bin/sh
set -eu
task_dir=$(mktemp -d /tmp/cudy-led-lifecycle.XXXXXX)
trap 'rm -rf "$task_dir"' EXIT
mkdir -p "$task_dir/bin" "$task_dir/run" "$task_dir/locks"
export CUDY_TEST_TASK_DIR="$task_dir"
python3 - "$task_dir" <<'PY'
from pathlib import Path
import sys
root=Path('tr3600/luci-app-cudy-led/root')
replacements={'/var/run/cudy-led':sys.argv[1]+'/run','/var/lock/cudy-led.lock':sys.argv[1]+'/locks/cudy-led.lock','/usr/libexec/cudy-led-control':sys.argv[1]+'/bin/control','/etc/init.d/cudy_led':sys.argv[1]+'/bin/service','/tmp/.failsafe':sys.argv[1]+'/failsafe'}
for name,path in [('init','etc/init.d/cudy_led'),('upgrade','usr/libexec/cudy-led-upgrade'),('ntp','etc/hotplug.d/ntp/95-cudy-led')]:
    data=(root/path).read_text()
    for old,new in replacements.items(): data=data.replace(old,new)
    Path(sys.argv[1]+'/'+name).write_text(data)
PY
cat > "$task_dir/bin/control" <<'SH'
#!/bin/sh
echo "control:$1" >> "$CUDY_TEST_TASK_DIR/events"
[ "${CUDY_TEST_INVALID:-0}" != 1 ]
SH
cat > "$task_dir/bin/service" <<'SH'
#!/bin/sh
# A suspend marker must exist before stopping the service.
case "$1" in suspend) exit 1;; stop) test -f "$CUDY_TEST_TASK_DIR/run/suspend";; start) test ! -e "$CUDY_TEST_TASK_DIR/run/suspend";; esac
echo "service:$1" >> "$CUDY_TEST_TASK_DIR/events"
SH
chmod +x "$task_dir/bin/control" "$task_dir/bin/service"
cat() { if [ "$1" = /tmp/sysinfo/board_name ]; then echo "${BOARD:-cudy,tr3600-v1}"; else command cat "$@"; fi; }
uci() { echo "${MODE:-status}"; }
procd_open_instance() { echo launch >> "$task_dir/events"; }
procd_set_param() { :; }
procd_close_instance() { :; }
. "$task_dir/init"
: > "$task_dir/events"
start_service
grep -q '^launch$' "$task_dir/events"
MODE=default; : > "$task_dir/events"; start_service; ! grep -q '^launch$' "$task_dir/events"
MODE=status; touch "$task_dir/failsafe"; : > "$task_dir/events"; start_service; test ! -s "$task_dir/events"; rm "$task_dir/failsafe"
BOARD=other,router; start_service; test ! -s "$task_dir/events"; unset BOARD
CUDY_TEST_INVALID=1; export CUDY_TEST_INVALID
if start_service; then echo 'Invalid configuration launched' >&2; exit 1; fi
unset CUDY_TEST_INVALID
# Restore occurs only after the singleton daemon lock has been released.
(exec 9>"$task_dir/locks/cudy-led.lock"; flock 9; touch "$task_dir/locked"; sleep 1) &
holder=$!
while [ ! -e "$task_dir/locked" ]; do sleep 1; done
stop_service; service_stopped; wait "$holder"
grep -q '^control:restore$' "$task_dir/events"
set -- suspend; . "$task_dir/upgrade"
test -f "$task_dir/run/suspend"
: > "$task_dir/events"; service_stopped; test ! -s "$task_dir/events"
set -- resume; . "$task_dir/upgrade"
test ! -e "$task_dir/run/suspend"
grep -q '^service:start$' "$task_dir/events"
ACTION=stratum stratum=3; . "$task_dir/ntp"; test -f "$task_dir/run/clock-synced"
ACTION=stratum stratum=16; . "$task_dir/ntp"; test ! -e "$task_dir/run/clock-synced"
echo 'LED lifecycle: defaults, board/failsafe guards, restore lock, upgrade handoff and NTP state passed'
