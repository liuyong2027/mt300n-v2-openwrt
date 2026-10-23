#!/bin/sh
set -eu
# Execute the real shell controller against isolated files, real private flock
# locks and substituted UCI/nft helpers. Never access the router's live rules.
source=${1:?guard script required}
test_dir=$(mktemp -d /tmp/cudy-ss-guard-test-XXXXXX)
case "$test_dir" in /tmp/cudy-ss-guard-test-*) ;; *) exit 1;; esac
cleanup() {
    rm -f "$test_dir/bin/uci" "$test_dir/bin/nft" "$test_dir/guard" "$test_dir/helper" "$test_dir/lock" \
        "$test_dir/events" "$test_dir/state" "$test_dir/enabled" "$test_dir/nft-fail" "$test_dir/operation.lock" \
        "$test_dir/etc/guard.nft" "$test_dir"/etc/.guard.* "$test_dir/locks/cudy-ss-guard.lock"
    rmdir "$test_dir/bin" "$test_dir/etc" "$test_dir/locks" "$test_dir"
}
trap cleanup EXIT HUP INT TERM
mkdir "$test_dir/bin" "$test_dir/etc" "$test_dir/locks"
export CUDY_GUARD_FIXTURE="$test_dir"
PATH="$test_dir/bin:$PATH"; export PATH
unset MANGO_OPERATION_LOCK
sed -e "s|/usr/libexec/cudy-ss-zt-guard|$test_dir/guard|g" \
    -e "s|/usr/libexec/cudy-ss-zt|$test_dir/helper|g" \
    -e "s|/usr/libexec/mango-lock|$test_dir/lock|g" \
    -e "s|/var/lock/mango-operation.lock|$test_dir/operation.lock|g" \
    -e "s|/etc/cudy-ss|$test_dir/etc|g" \
    -e "s|/var/lock|$test_dir/locks|g" "$source" > "$test_dir/guard"
cat > "$test_dir/lock" <<'LOCK'
#!/bin/sh
set -eu
echo lock >> "$CUDY_GUARD_FIXTURE/events"
exec 9>"$CUDY_GUARD_FIXTURE/operation.lock"
flock -n 9 || exit 75
MANGO_OPERATION_LOCK=1; export MANGO_OPERATION_LOCK
"$@"
LOCK
cat > "$test_dir/helper" <<'HELPER'
#!/bin/sh
set -eu
state=$(cat "$CUDY_GUARD_FIXTURE/state")
case "$1" in
    guard-ok)
        echo "check:${MANGO_OPERATION_LOCK:-0}" >> "$CUDY_GUARD_FIXTURE/events"
        [ "$state" = valid ] && exit 0
        [ "$state" = valid-after-lock ] && [ "${MANGO_OPERATION_LOCK:-0}" = 1 ] && exit 0
        exit 1;;
    guard) printf 'fixture-rules\n';;
    *) exit 99;;
esac
HELPER
cat > "$test_dir/bin/uci" <<'UCI'
#!/bin/sh
[ "$*" = '-q get cudy_ss.main.enabled' ] || exit 98
cat "$CUDY_GUARD_FIXTURE/enabled"
UCI
cat > "$test_dir/bin/nft" <<'NFT'
#!/bin/sh
set -eu
case "$*" in
    '-c -f '*) action=validate;;
    '-f '*) action=apply;;
    *) exit 97;;
esac
echo "$action" >> "$CUDY_GUARD_FIXTURE/events"
[ ! -f "$CUDY_GUARD_FIXTURE/nft-fail" ] || [ "$(cat "$CUDY_GUARD_FIXTURE/nft-fail")" != "$action" ] || exit 42
NFT
chmod 700 "$test_dir/guard" "$test_dir/lock" "$test_dir/helper" "$test_dir/bin/uci" "$test_dir/bin/nft"
reset_case() {
    : > "$test_dir/events"
    echo 1 > "$test_dir/enabled"
    echo "$1" > "$test_dir/state"
    printf 'previous-rules\n' > "$test_dir/etc/guard.nft"
    rm -f "$test_dir/nft-fail"
}
fail() { echo "FAIL $*" >&2; exit 1; }
no_mutation() {
    ! grep -Eq '^(validate|apply)$' "$test_dir/events" || fail 'unexpected nft change'
    [ "$(cat "$test_dir/etc/guard.nft")" = previous-rules ] || fail 'guard file changed'
}
count() { grep -c "^$1$" "$test_dir/events" || :; }
reset_case valid
exec 7>"$test_dir/operation.lock"; flock -x 7
rc=0; "$test_dir/guard" || rc=$?
flock -u 7; exec 7>&-
[ "$rc" = 0 ] || fail 'healthy guard contended on operation lock'
[ "$(count lock)" = 0 ] || fail 'healthy guard acquired operation lock'
no_mutation
echo 'PASS healthy guard returns without contending on an already-held operation lock'

reset_case invalid
exec 7>"$test_dir/operation.lock"; flock -x 7
rc=0; "$test_dir/guard" || rc=$?
flock -u 7; exec 7>&-
[ "$rc" = 75 ] && [ "$(count lock)" = 1 ] || fail 'invalid guard bypassed operation lock'
no_mutation
echo 'PASS invalid guard still requires operation lock before any mutation'

reset_case valid-after-lock
"$test_dir/guard"
[ "$(count lock)" = 1 ] && [ "$(count check:0)" = 1 ] && [ "$(count check:1)" = 1 ] || fail 'missing recheck under lock'
no_mutation
echo 'PASS rules fixed by another operation are rechecked under the lock'

reset_case invalid
"$test_dir/guard"
[ "$(count lock)" = 1 ] && [ "$(count validate)" = 1 ] && [ "$(count apply)" = 1 ] || fail 'missing locked repair'
[ "$(tail -n 2 "$test_dir/events")" = "$(printf 'validate\napply')" ] || fail 'apply preceded validation'
[ "$(cat "$test_dir/etc/guard.nft")" = fixture-rules ] || fail 'new guard not saved'
echo 'PASS invalid rules are validated, applied and saved only under the lock'

for action in validate apply; do
    reset_case invalid; echo "$action" > "$test_dir/nft-fail"
    rc=0; "$test_dir/guard" || rc=$?
    [ "$rc" = 42 ] || fail 'nft error ignored'
    [ "$(cat "$test_dir/etc/guard.nft")" = previous-rules ] || fail 'failed nft change overwrote guard file'
    if [ "$action" = validate ]; then [ "$(count apply)" = 0 ] || fail 'applied invalid rules'; fi
    for path in "$test_dir"/etc/.guard.*; do [ ! -e "$path" ] || fail 'temporary rule file leaked'; done
    echo "PASS $action failure preserves guard record and removes temporary files"
done

reset_case valid
"$test_dir/lock" "$test_dir/guard"
[ "$(count lock)" = 1 ] && [ "$(count check:1)" = 1 ] || fail 'inherited lock handling changed'
no_mutation
echo 'PASS caller-owned operation lock remains supported'

reset_case invalid
exec 7>"$test_dir/operation.lock"; flock -x 7
rc=0; MANGO_OPERATION_LOCK=1 "$test_dir/guard" || rc=$?
flock -u 7; exec 7>&-
[ "$rc" = 75 ] || fail 'environment flag without a valid FD bypassed locking'
no_mutation
echo 'PASS forged inherited-lock flag does not bypass file-descriptor validation'

reset_case invalid; echo 0 > "$test_dir/enabled"
"$test_dir/guard"
no_mutation
echo 'PASS disabled service does not install firewall rules'
