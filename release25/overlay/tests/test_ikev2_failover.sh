#!/bin/sh
# Failover counter: two failed dials switch to the other server.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
fail=$(mktemp -d)
trap 'rm -rf "$fail"' EXIT
mkdir -p "$fail/bin" "$fail/state"
cat > "$fail/bin/uci" <<'EOF'
#!/bin/sh
opt=${3##*.}
case "$opt" in
    enabled) echo 1 ;;
    mode) echo split ;;
    server2) printf '%s\n' "${FAKE_SERVER2-}" ;;
esac
EOF
cat > "$fail/bin/swanctl" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_LOG"
case "$1" in
    --list-sas)
        cat "$FAKE_SAS"
        ;;
    --initiate)
        if [ "${FAKE_INITIATE_OK-0}" = 1 ]; then
            exit 0
        fi
        exit 1
        ;;
esac
exit 0
EOF
chmod +x "$fail/bin/uci" "$fail/bin/swanctl"
export PATH="$fail/bin:$PATH"
export MANGO_IKEV2_STATE="$fail/state"
export FAKE_LOG="$fail/log"
export FAKE_SAS="$fail/sas"
run() {
    : > "$FAKE_LOG"
    sh "$root/package/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-failover"
}

# Primary is up: no dial, counter cleared.
export FAKE_SERVER2=backup.example.com
printf '%s\n' 'mango: #1, ESTABLISHED, IKEv2' > "$FAKE_SAS"
echo 4 > "$fail/state/fail-count"
echo mango > "$fail/state/active"
export FAKE_INITIATE_OK=0
run
grep -q -- '--initiate' "$FAKE_LOG" && exit 1
test "$(cat "$fail/state/fail-count")" = 0
test "$(cat "$fail/state/active")" = mango

# First failure stays on the primary.
printf '%s\n' 'mango: #2, CONNECTING' > "$FAKE_SAS"
echo 0 > "$fail/state/fail-count"
run
test "$(cat "$fail/state/fail-count")" = 1
test "$(cat "$fail/state/active")" = mango
grep -q -- '--initiate --ike mango ' "$FAKE_LOG"

# Second failure switches and dials the backup.
echo 1 > "$fail/state/fail-count"
run
test "$(cat "$fail/state/active")" = mango2
test "$(cat "$fail/state/fail-count")" = 1
grep -q -- '--initiate --ike mango2 ' "$FAKE_LOG"

# Backup up: stay there.
printf '%s\n' 'mango2: #3, ESTABLISHED, IKEv2' > "$FAKE_SAS"
echo 1 > "$fail/state/fail-count"
run
test "$(cat "$fail/state/active")" = mango2
test "$(cat "$fail/state/fail-count")" = 0
grep -q -- '--initiate' "$FAKE_LOG" && exit 1

# No backup: two failures do not switch away.
unset FAKE_SERVER2
export FAKE_SERVER2=
printf '%s\n' 'mango: #4, CONNECTING' > "$FAKE_SAS"
echo mango > "$fail/state/active"
echo 1 > "$fail/state/fail-count"
run
test "$(cat "$fail/state/active")" = mango
test "$(cat "$fail/state/fail-count")" = 2

echo PASS IKEv2 failover switches after two failures
