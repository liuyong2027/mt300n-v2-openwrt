#!/bin/sh
# Healthy IKEv2 recheck must not flush xfrm-mango. Dial and dead-tunnel paths still do.
# A single lost ICMP ping is not a dead datapath: HTTP 2xx counts, and the SA
# stays up until three consecutive probe misses.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
script=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-failover
tmp=$(mktemp -d)
swanctl_etc_before=0
[ -e /etc/swanctl ] && swanctl_etc_before=1
cleanup() {
	rm -rf "$tmp"
	if [ "$swanctl_etc_before" = 0 ] && [ -d /etc/swanctl ]; then
		rm -rf /etc/swanctl
	fi
}
trap cleanup EXIT
mkdir -p "$tmp/bin" "$tmp/state"
printf '%s\n' mango > "$tmp/state/active"
printf '%s\n' mango > "$tmp/state/logged-up"
printf '%s\n' 2 > "$tmp/state/datapath-fail"

cat > "$tmp/bin/uci" << 'EOF'
#!/bin/sh
key=${3-}
case "$key" in
	mango_ikev2.main.enabled) printf '%s\n' 1 ;;
	mango_ikev2.main.mode) printf '%s\n' split ;;
	*) exit 1 ;;
esac
EOF
cat > "$tmp/bin/swanctl" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${SWANCTL_LOG:?}"
if [ "${1-}" = --list-sas ]; then
	cat << 'SAS'
mango: #1, ESTABLISHED, IKEv2
  local 192.0.2.1[10.5.0.2]
  remote vpn.example[203.0.113.5]
  mango: #1, INSTALLED, TUNNEL
    local  10.5.0.2/32
    remote 0.0.0.0/0
SAS
	exit 0
fi
exit 1
EOF
cat > "$tmp/bin/ip" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${IP_LOG:?}"
case "$*" in
	*"-4 addr show"*)
		printf '%s\n' 'inet 10.5.0.2/32 scope global xfrm-mango'
		;;
	*"-4 rule show"*)
		printf '%s\n' '10001: from all fwmark 0x101 lookup 101'
		;;
esac
exit 0
EOF
cat > "$tmp/bin/ping" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${PING_LOG:?}"
exit "${PING_RC:-0}"
EOF
cat > "$tmp/bin/curl" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${CURL_LOG:?}"
url=
for a in "$@"; do url=$a; done
case "$url" in
	*gstatic.com/generate_204)
		printf '%s' "${CURL_GSTATIC:-204}"
		exit "${CURL_GSTATIC_RC:-0}"
		;;
	*google.com/generate_204)
		printf '%s' "${CURL_GOOGLE:-204}"
		exit "${CURL_GOOGLE_RC:-0}"
		;;
esac
printf '%s' 000
exit 1
EOF
chmod 755 "$tmp/bin/uci" "$tmp/bin/swanctl" "$tmp/bin/ip" "$tmp/bin/ping" "$tmp/bin/curl"

IP_LOG=$tmp/ip.log
SWANCTL_LOG=$tmp/swanctl.log
PING_LOG=$tmp/ping.log
CURL_LOG=$tmp/curl.log
export IP_LOG SWANCTL_LOG PING_LOG CURL_LOG
: > "$IP_LOG"
: > "$SWANCTL_LOG"
: > "$PING_LOG"
: > "$CURL_LOG"
PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state \
	sh "$script"
if grep -q -- '-4 addr flush' "$IP_LOG"; then
	printf '%s\n' 'healthy recheck flushed xfrm-mango' >&2
	cat "$IP_LOG" >&2
	exit 1
fi
grep -q -- '-4 addr show' "$IP_LOG"
if grep -q -- 'addr replace' "$IP_LOG"; then
	printf '%s\n' 'healthy recheck replaced an address that was already present' >&2
	exit 1
fi
if grep -q -- '--terminate' "$SWANCTL_LOG"; then
	printf '%s\n' 'healthy recheck tore down the IKE SA' >&2
	exit 1
fi
if [ -s "$CURL_LOG" ]; then
	printf '%s\n' 'ICMP success should not fall through to HTTP' >&2
	exit 1
fi
test "$(cat "$tmp/state/active")" = mango
test "$(cat "$tmp/state/fail-count")" = 0
test "$(cat "$tmp/state/datapath-fail")" = 0
test "$(cat "$tmp/state/logged-up")" = mango

reset_logs() {
	: > "$IP_LOG"
	: > "$SWANCTL_LOG"
	: > "$PING_LOG"
	: > "$CURL_LOG"
}

# Both ICMP probes fail. gstatic is not 2xx; Google generate_204 is.
PING_RC=1
CURL_GSTATIC=404
CURL_GOOGLE=204
export PING_RC CURL_GSTATIC CURL_GOOGLE
printf '%s\n' 2 > "$tmp/state/datapath-fail"
reset_logs
PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state \
	sh "$script"
if grep -q -- '-4 addr flush' "$IP_LOG" || grep -q -- '--terminate' "$SWANCTL_LOG"; then
	printf '%s\n' 'HTTP 2xx was treated as a dead datapath' >&2
	exit 1
fi
grep -q 'gstatic.com/generate_204' "$CURL_LOG"
grep -q 'google.com/generate_204' "$CURL_LOG"
grep -q -- '--interface xfrm-mango' "$CURL_LOG"
test "$(cat "$tmp/state/datapath-fail")" = 0
test "$(cat "$tmp/state/logged-up")" = mango

# Non-2xx HTTP after lost ICMP keeps the SA for the first two misses.
CURL_GSTATIC=500
CURL_GOOGLE=000
CURL_GOOGLE_RC=1
export CURL_GSTATIC CURL_GOOGLE CURL_GOOGLE_RC
printf '%s\n' 0 > "$tmp/state/datapath-fail"
miss=1
while [ "$miss" -le 2 ]; do
	reset_logs
	PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state \
		sh "$script"
	if grep -q -- '-4 addr flush' "$IP_LOG" || grep -q -- '--terminate' "$SWANCTL_LOG"; then
		printf '%s\n' "datapath miss $miss tore down the SA" >&2
		exit 1
	fi
	test "$(cat "$tmp/state/datapath-fail")" = "$miss"
	test "$(cat "$tmp/state/logged-up")" = mango
	test "$(cat "$tmp/state/active")" = mango
	miss=$((miss + 1))
done

# The third consecutive miss redials and flushes the VIP. Dial itself may
# stop at the swanctl directory; terminate and the flush already happened.
reset_logs
set +e
PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state \
	sh "$script" >/dev/null 2>"$tmp/redial.err"
set -e
grep -q -- '--terminate --ike mango' "$SWANCTL_LOG"
grep -q -- '-4 addr flush dev xfrm-mango' "$IP_LOG"
test "$(cat "$tmp/state/datapath-fail")" = 0
test ! -f "$tmp/state/logged-up"

python3 - "$script" << 'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
assert text.count("clear_vip") == 4, text.count("clear_vip")
assert "prepare_dial() {\n\tclear_vip\n" in text
assert '\tvip=$(peer_vip "$peer")\n\tclear_vip\n\tpin_vip "$vip"\n' in text
assert 'log_event fail "$active" "datapath dead; redial"\n\tterminate_all\n\tclear_vip\n' in text
assert "http_probe https://www.gstatic.com/generate_204" in text
assert "http_probe https://www.google.com/generate_204" in text
assert 'datapath probe failed (#$n/3); keep SA' in text
assert '[ "$n" -lt 3 ]' in text
start = text.index("\tif datapath_ok; then\n")
end = text.index("\tfi\n\t# SA looks fine but tunnel probe failed", start)
healthy = text[start:end]
assert "clear_vip" not in healthy
assert '\tpin_vip "$vip"\n' in healthy
assert "reset_datapath_fail" in healthy
print("healthy recheck keeps the VIP; HTTP 2xx counts; three misses redial")
PY
