#!/bin/sh
set -eu
candidate=$1
common=$2
root=$3/test-wrapper
mkdir -p "$root/bin" "$root/mango" "$root/locks"
sed -e "s|/var/etc/mango|$root/mango|g" \
    -e "s|/var/lock|$root/locks|g" \
    -e "s|/usr/libexec/timeout-coreutils|$root/bin/timeout|g" \
    -e "s|/usr/libexec/mango-connectivity-probe|$common|g" \
    "$candidate" > "$root/probe.sh"
cat > "$root/bin/timeout" <<'EOF'
#!/bin/sh
[ "$3" != begin ] || printf 'test-token'
printf '%s\n' "$*" >> "$PROBE_TEST_CALLBACKS"
exit 0
EOF
cat > "$root/bin/curl" <<'EOF'
#!/bin/sh
for target; do :; done
printf '%s\n' "$target" >> "$PROBE_TEST_TARGETS"
[ "${PROBE_TEST_SCENARIO:-}" != failed ] || { printf '503 connect=0 tls=0 first=0 total=0'; exit 0; }
case "$target" in
    https://www.google.com/generate_204)
        printf '000 connect=0 tls=0 first=0 total=0'
        exit 7
        ;;
    https://www.bbc.com/robots.txt|https://cp.cloudflare.com/generate_204)
        printf '200 connect=0.01 tls=0.02 first=0.03 total=0.04'
        exit 0
        ;;
esac
exit 90
EOF
chmod 700 "$root/bin/curl" "$root/bin/timeout"
for mode in gfw split global direct; do
    printf '%s\nnode\n' "$mode" > "$root/mango/runtime-state"
    : > "$root/targets"
    : > "$root/callbacks"
    PATH="$root/bin:$PATH" PROBE_TEST_TARGETS="$root/targets" PROBE_TEST_CALLBACKS="$root/callbacks" sh "$root/probe.sh"
    [ "$(wc -l < "$root/targets")" -eq 2 ]
    [ "$(sed -n '1p' "$root/targets")" = https://www.google.com/generate_204 ]
    expected=https://cp.cloudflare.com/generate_204
    [ "$mode" != gfw ] || expected=https://www.bbc.com/robots.txt
    [ "$(sed -n '2p' "$root/targets")" = "$expected" ]
    grep -q 'finish test-token 0' "$root/callbacks"
    grep -q 'result=ok' "$root/mango/probe-history"
done
printf 'gfw\nnode\n' > "$root/mango/runtime-state"
: > "$root/callbacks"
rc=0
PATH="$root/bin:$PATH" PROBE_TEST_TARGETS="$root/targets" PROBE_TEST_CALLBACKS="$root/callbacks" PROBE_TEST_SCENARIO=failed sh "$root/probe.sh" || rc=$?
[ "$rc" = 1 ]
grep -q 'finish test-token 1' "$root/callbacks"
grep -q 'result=failed.*rc=0 http=503' "$root/mango/probe-history"
printf 'PASS automatic-switch wrapper: shared targets, diagnostics, exit codes, and LED callbacks\n'
