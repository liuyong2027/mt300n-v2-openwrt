#!/bin/sh
set -eu
common=$1
root=$2/test-common
mkdir -p "$root/bin"
cat > "$root/bin/curl" <<'EOF'
#!/bin/sh
for target; do :; done
printf '%s\n' "$target" >> "$PROBE_TEST_TARGETS"
count=$(wc -l < "$PROBE_TEST_TARGETS")
printf '%s\n' "$@" > "$PROBE_TEST_ARGS.$count"
printf 'test diagnostic' >&2
case "$PROBE_TEST_SCENARIO" in
    first) printf '204 connect=0 tls=0 first=0 total=0'; exit 0 ;;
    fallback)
        if [ "$count" = 1 ]; then printf '000 connect=0 tls=0 first=0 total=0'; exit 7; fi
        printf '200 connect=0 tls=0 first=0 total=0'; exit 0
        ;;
    http-failure) printf '503 connect=0 tls=0 first=0 total=0'; exit 0 ;;
    transport-failure) printf '200 connect=0 tls=0 first=0 total=0'; exit 7 ;;
    redirect) printf '302 connect=0 tls=0 first=0 total=0'; exit 0 ;;
esac
exit 90
EOF
chmod 700 "$root/bin/curl"
value() { awk -v key="$2" '$0==key {getline;print;exit}' "$1"; }
cases=0
for mode in direct split global gfw; do
    for scenario in first fallback http-failure transport-failure redirect; do
        : > "$root/targets"
        rc=0
        PATH="$root/bin:$PATH" PROBE_TEST_TARGETS="$root/targets" \
            PROBE_TEST_ARGS="$root/args" PROBE_TEST_SCENARIO="$scenario" \
            sh "$common" "$mode" > "$root/report" || rc=$?
        count=$(wc -l < "$root/targets")
        case "$scenario" in
            first|redirect) [ "$rc" = 0 ]; [ "$count" = 1 ] ;;
            fallback) [ "$rc" = 0 ]; [ "$count" = 2 ] ;;
            *) [ "$rc" = 1 ]; [ "$count" = 2 ] ;;
        esac
        expected_first=https://www.google.com/generate_204
        expected_fallback=https://cp.cloudflare.com/generate_204
        if [ "$mode" = direct ]; then
            expected_first=https://www.baidu.com/
            expected_fallback=https://www.qq.com/
            [ "$(value "$root/args.1" --noproxy)" = '*' ]
            grep -Fxq -- --head "$root/args.1"
            [ "$(value "$root/args.1" --connect-timeout)" = 3 ]
            [ "$(value "$root/args.1" --max-time)" = 5 ]
            ! grep -Fxq -- --proxy "$root/args.1"
        else
            [ "$mode" != gfw ] || expected_fallback=https://www.bbc.com/robots.txt
            [ "$(value "$root/args.1" --proxy)" = socks5h://127.0.0.1:10809 ]
            [ "$(value "$root/args.1" --connect-timeout)" = 4 ]
            [ "$(value "$root/args.1" --max-time)" = 8 ]
            [ "$(value "$root/args.1" --max-filesize)" = 65536 ]
            ! grep -Fxq -- --head "$root/args.1"
        fi
        [ "$(sed -n '1p' "$root/targets")" = "$expected_first" ]
        if [ "$count" = 2 ]; then [ "$(sed -n '2p' "$root/targets")" = "$expected_fallback" ]; fi
        grep -q 'error=test diagnostic' "$root/report"
        if [ "$scenario" = transport-failure ]; then grep -q 'rc=7 http=200' "$root/report"; fi
        cases=$((cases+1))
    done
done
: > "$root/targets"
rc=0
PATH="$root/bin:$PATH" PROBE_TEST_TARGETS="$root/targets" sh "$common" unsupported > "$root/report" || rc=$?
[ "$rc" = 2 ]
[ ! -s "$root/targets" ]
printf 'PASS common probe: %s mode/scenario cases, request options, fallback order, and invalid mode\n' "$cases"
