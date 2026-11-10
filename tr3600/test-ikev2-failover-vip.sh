#!/bin/sh
# Healthy IKEv2 recheck must not flush xfrm-mango. Dial and dead-tunnel paths still do.
# A single lost ICMP ping is not a dead datapath: HTTP 2xx counts, and the SA
# stays up until three consecutive probe misses.
# A child rekey lists the old REKEYED SA and the new INSTALLED SA together.
# That overlap stays healthy and must not flush. INTERNAL_ADDRESS_FAILURE
# switches to the next server and does not count toward SSR fallback.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
script=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-failover
log_script=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-log
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
printf '%s\n' 0 > "$tmp/state/fail-count"
printf '%s\n' 0 > "$tmp/state/fallback-fail"

cat > "$tmp/bin/uci" << 'EOF'
#!/bin/sh
key=${3-}
case "$key" in
	mango_ikev2.main.enabled) printf '%s\n' 1 ;;
	mango_ikev2.main.mode) printf '%s\n' split ;;
	mango_ikev2.main.server2)
		if [ -n "${UCI_SERVER2:-}" ]; then
			printf '%s\n' "$UCI_SERVER2"
			exit 0
		fi
		exit 1
		;;
	mango_ikev2.main.server3)
		if [ -n "${UCI_SERVER3:-}" ]; then
			printf '%s\n' "$UCI_SERVER3"
			exit 0
		fi
		exit 1
		;;
	mango_ikev2.main.ssr_fallback) printf '%s\n' 1 ;;
	mango_ikev2.main.ssr_fallback_fails) printf '%s\n' 6 ;;
	*) exit 1 ;;
esac
EOF
cat > "$tmp/sas" << 'EOF'
mango: #1, ESTABLISHED, IKEv2
  local 192.0.2.1[10.5.0.2]
  remote vpn.example[203.0.113.5]
  mango: #1, INSTALLED, TUNNEL
    local  10.5.0.2/32
    remote 0.0.0.0/0
EOF
cat > "$tmp/bin/swanctl" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${SWANCTL_LOG:?}"
cmd=${1-}
shift || true
case "$cmd" in
	--list-sas)
		if [ -f "${SWANCTL_DOWN:-}" ]; then
			exit 0
		fi
		cat "${SAS_FILE:?}"
		exit 0
		;;
	--terminate)
		if [ "${SWANCTL_KEEP_SA:-}" = 1 ]; then
			exit 0
		fi
		touch "${SWANCTL_DOWN:?}"
		exit 0
		;;
	--initiate)
		peer=
		prev=
		for a in "$@"; do
			if [ "$prev" = --ike ] || [ "$prev" = --child ]; then
				peer=$a
				break
			fi
			prev=$a
		done
		iaf=0
		if [ -n "${IAF_PEERS:-}" ]; then
			case " $IAF_PEERS " in
				*" $peer "*) iaf=1 ;;
			esac
		fi
		if [ "$iaf" = 1 ]; then
			if [ -n "${INITIATE_CHARON_APPEND_FILE:-}" ] && [ -f "$INITIATE_CHARON_APPEND_FILE" ]; then
				cat "$INITIATE_CHARON_APPEND_FILE" >> "${MANGO_IKEV2_CHARON_LOG:?}"
			else
				printf '%s\n' '[IKE] received INTERNAL_ADDRESS_FAILURE notify, no CHILD_SA built' >> "${MANGO_IKEV2_CHARON_LOG:?}"
			fi
			printf '%s\n' 'initiate failed: INTERNAL_ADDRESS_FAILURE' >&2
			exit 1
		fi
		if [ -n "${INITIATE_STDERR_FILE:-}" ] && [ -f "$INITIATE_STDERR_FILE" ]; then
			cat "$INITIATE_STDERR_FILE" >&2
			exit 1
		fi
		rm -f "${SWANCTL_DOWN:-}"
		if [ -n "${SAS_AFTER_INITIATE:-}" ] && [ -f "$SAS_AFTER_INITIATE" ]; then
			cp "$SAS_AFTER_INITIATE" "$SAS_FILE"
		fi
		exit 0
		;;
	--load-conns|--load-all)
		exit 0
		;;
esac
exit 0
EOF
cat > "$tmp/bin/ip" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${IP_LOG:?}"
case "$*" in
	*"-4 addr show"*)
		if [ -n "${IP_ADDR_SHOW+x}" ]; then
			printf '%s\n' "$IP_ADDR_SHOW"
		else
			printf '%s\n' 'inet 10.5.0.2/32 scope global xfrm-mango'
		fi
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
SAS_FILE=$tmp/sas
SWANCTL_DOWN=$tmp/swan-down
export IP_LOG SWANCTL_LOG PING_LOG CURL_LOG SAS_FILE SWANCTL_DOWN
export MANGO_IKEV2_LOCK=$tmp/failover.lock
export MANGO_IKEV2_LOCK_WAIT=5
export MANGO_IKEV2_POST_TERM_WAIT=0
export MANGO_IKEV2_SA_POLL=0
export MANGO_IKEV2_SNIP=$tmp/snip
export MANGO_IKEV2_CHARON_LOG=$tmp/charon.log
export MANGO_IKEV2_INT_ADDR_BACKOFF=45
: > "$IP_LOG"
: > "$SWANCTL_LOG"
: > "$PING_LOG"
: > "$CURL_LOG"
: > "$MANGO_IKEV2_CHARON_LOG"

reset_logs() {
	: > "$IP_LOG"
	: > "$SWANCTL_LOG"
	: > "$PING_LOG"
	: > "$CURL_LOG"
}

run_failover() {
	PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state \
		sh "$script" >/dev/null 2>"$tmp/run.err"
}

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
if grep -q -- '-4 addr flush' "$IP_LOG" && ! grep -q -- '--terminate' "$SWANCTL_LOG"; then
	printf '%s\n' 'flush ran without a terminate' >&2
	exit 1
fi

# Terminate left the IKE SA up. The 3-miss count must stay put so the next
# tick redials again instead of starting over at probe #1/3.
rm -f "$SWANCTL_DOWN"
printf '%s\n' 2 > "$tmp/state/datapath-fail"
printf '%s\n' mango > "$tmp/state/active"
printf '%s\n' mango > "$tmp/state/logged-up"
SWANCTL_KEEP_SA=1
export SWANCTL_KEEP_SA
reset_logs
PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state \
	sh "$script" >/dev/null 2>"$tmp/skip-redial.err"
grep -q -- '--terminate --ike mango' "$SWANCTL_LOG"
if grep -q -- '-4 addr flush' "$IP_LOG" || grep -q -- '--initiate' "$SWANCTL_LOG"; then
	printf '%s\n' 'stuck SA after terminate still flushed or redialed' >&2
	cat "$IP_LOG" "$SWANCTL_LOG" >&2
	exit 1
fi
test "$(cat "$tmp/state/datapath-fail")" = 3
reset_logs
PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state \
	sh "$script" >/dev/null 2>"$tmp/skip-redial2.err"
grep -q -- '--terminate --ike mango' "$SWANCTL_LOG"
if grep -q -- '-4 addr flush' "$IP_LOG" || grep -q -- '--initiate' "$SWANCTL_LOG"; then
	printf '%s\n' 'second tick after a stuck SA waited for more probe misses' >&2
	cat "$IP_LOG" "$SWANCTL_LOG" >&2
	exit 1
fi
test "$(cat "$tmp/state/datapath-fail")" = 4
unset SWANCTL_KEEP_SA

# Rekey overlap: old child is REKEYED and the new one is INSTALLED past the
# old 8-line window. The tick is healthy, prefers the IKE VIP, and does not flush.
cat > "$tmp/rekey.sas" << 'EOF'
mango: #12, ESTABLISHED, IKEv2, aaaa_i* bbbb_r
  local  'vpn-user' @ 192.0.2.10[4500] [10.6.0.17]
  remote 'nordvpn' @ 203.0.113.5[4500]
  AES_CBC-256/HMAC_SHA2_256_128/PRF_HMAC_SHA2_256/ECP_256
  established 4000s ago, rekeying in 2000s
  mango: #25, reqid 1, REKEYED, TUNNEL, ESP:AES_GCM_16-256
    installed 1800s ago, rekeying in 0s, expires in 5s
    in  c1a2b3c4, 1000 bytes, 10 packets, 1s ago
    out d5e6f7a8, 2000 bytes, 20 packets, 1s ago
    local  10.9.9.9/32
    remote 0.0.0.0/0
  mango: #26, reqid 2, INSTALLED, TUNNEL, ESP:AES_GCM_16-256
    installed 1s ago, rekeying in 1400s, expires in 3000s
    in  a1b2c3d4, 0 bytes, 0 packets
    out e5f6a7b8, 0 bytes, 0 packets
    local  10.9.9.9/32
    remote 0.0.0.0/0
EOF
if grep -A8 '^mango: .*ESTABLISHED' "$tmp/rekey.sas" | grep -q INSTALLED; then
	printf '%s\n' 'rekey fixture no longer misses INSTALLED inside 8 lines' >&2
	exit 1
fi
cp "$tmp/rekey.sas" "$SAS_FILE"
rm -f "$SWANCTL_DOWN" "$tmp/state/int-addr-until"
printf '%s\n' 2 > "$tmp/state/datapath-fail"
printf '%s\n' mango > "$tmp/state/active"
printf '%s\n' 0 > "$tmp/state/fail-count"
PING_RC=0
export PING_RC
IP_ADDR_SHOW='inet 10.1.1.1/32 scope global xfrm-mango'
export IP_ADDR_SHOW
unset INITIATE_STDERR_FILE INITIATE_CHARON_APPEND_FILE SAS_AFTER_INITIATE UCI_SERVER2 || true
reset_logs
run_failover
if grep -q -- '-4 addr flush' "$IP_LOG"; then
	printf '%s\n' 'rekey overlap flushed xfrm-mango' >&2
	cat "$IP_LOG" >&2
	exit 1
fi
if grep -q -- '--terminate' "$SWANCTL_LOG" || grep -q -- '--initiate' "$SWANCTL_LOG"; then
	printf '%s\n' 'rekey overlap tore down or redialed' >&2
	cat "$SWANCTL_LOG" >&2
	exit 1
fi
grep -q -- 'addr del 10.1.1.1' "$IP_LOG"
grep -q -- 'addr replace 10.6.0.17/32' "$IP_LOG"
if grep -q -- '10.9.9.9' "$IP_LOG"; then
	printf '%s\n' 'rekey overlap pinned the child TS instead of the IKE VIP' >&2
	exit 1
fi
test "$(cat "$tmp/state/datapath-fail")" = 0
test "$(cat "$tmp/state/active")" = mango
test "$(cat "$tmp/state/fail-count")" = 0

# REKEYED with no INSTALLED child yet: skip the tick. Do not probe, flush, or dial.
cat > "$tmp/rekey-only.sas" << 'EOF'
mango: #12, ESTABLISHED, IKEv2, aaaa_i* bbbb_r
  local  'vpn-user' @ 192.0.2.10[4500] [10.6.0.17]
  remote 'nordvpn' @ 203.0.113.5[4500]
  AES_CBC-256/HMAC_SHA2_256_128/PRF_HMAC_SHA2_256/ECP_256
  established 10s ago, rekeying in 10s
  mango: #25, reqid 1, REKEYED, TUNNEL, ESP:AES_GCM_16-256
    installed 1800s ago, rekeying in 0s, expires in 5s
    in  c1a2b3c4, 1 bytes, 1 packets
    out d5e6f7a8, 1 bytes, 1 packets
    local  10.6.0.17/32
    remote 0.0.0.0/0
EOF
cp "$tmp/rekey-only.sas" "$SAS_FILE"
printf '%s\n' 2 > "$tmp/state/datapath-fail"
unset IP_ADDR_SHOW || true
reset_logs
run_failover
if grep -q -- '-4 addr flush' "$IP_LOG" || grep -q -- '--initiate' "$SWANCTL_LOG" || grep -q -- '--terminate' "$SWANCTL_LOG"; then
	printf '%s\n' 'transitional REKEYED child was acted on' >&2
	exit 1
fi
test "$(cat "$tmp/state/datapath-fail")" = 2
test "$(cat "$tmp/state/fail-count")" = 0

# IKE SA up, child missing: initiate only the child and do not flush.
cat > "$tmp/child-missing.sas" << 'EOF'
mango: #4, ESTABLISHED, IKEv2, aaaa_i* bbbb_r
  local  'vpn-user' @ 192.0.2.10[4500] [10.7.0.8]
  remote 'nordvpn' @ 203.0.113.5[4500]
  AES_CBC-256/HMAC_SHA2_256_128/PRF_HMAC_SHA2_256/ECP_256
  established 20s ago, rekeying in 3000s
EOF
cat > "$tmp/child-up.sas" << 'EOF'
mango: #4, ESTABLISHED, IKEv2, aaaa_i* bbbb_r
  local  'vpn-user' @ 192.0.2.10[4500] [10.7.0.8]
  remote 'nordvpn' @ 203.0.113.5[4500]
  AES_CBC-256/HMAC_SHA2_256_128/PRF_HMAC_SHA2_256/ECP_256
  established 20s ago, rekeying in 3000s
  mango: #9, reqid 1, INSTALLED, TUNNEL, ESP:AES_GCM_16-256
    installed 0s ago, rekeying in 1000s, expires in 2000s
    in  a1b2c3d4, 0 bytes, 0 packets
    out e5f6a7b8, 0 bytes, 0 packets
    local  10.7.0.8/32
    remote 0.0.0.0/0
EOF
cp "$tmp/child-missing.sas" "$SAS_FILE"
SAS_AFTER_INITIATE=$tmp/child-up.sas
export SAS_AFTER_INITIATE
unset INITIATE_STDERR_FILE INITIATE_CHARON_APPEND_FILE || true
IP_ADDR_SHOW=
export IP_ADDR_SHOW
printf '%s\n' 0 > "$tmp/state/datapath-fail"
printf '%s\n' 1 > "$tmp/state/fail-count"
reset_logs
run_failover
if grep -q -- '-4 addr flush' "$IP_LOG"; then
	printf '%s\n' 'child-only repair flushed while the IKE SA existed' >&2
	cat "$IP_LOG" >&2
	exit 1
fi
if grep -q -- '--initiate --ike' "$SWANCTL_LOG"; then
	printf '%s\n' 'child-only repair initiated a new IKE SA' >&2
	cat "$SWANCTL_LOG" >&2
	exit 1
fi
grep -q -- '--initiate --child mango' "$SWANCTL_LOG"
grep -q -- 'addr replace 10.7.0.8/32' "$IP_LOG"
test "$(cat "$tmp/state/active")" = mango
test "$(cat "$tmp/state/fail-count")" = 0
test ! -f "$tmp/state/int-addr-until"

# A successful recheck clears a previous address-failure round.
printf '%s\n' 'mango mango2' > "$tmp/state/int-addr-round"
echo $(( $(date +%s) + 60 )) > "$tmp/state/int-addr-until"
reset_logs
run_failover
test ! -f "$tmp/state/int-addr-round"
test ! -f "$tmp/state/int-addr-until"
test "$(cat "$tmp/state/active")" = mango

# INTERNAL_ADDRESS_FAILURE on the primary switches to mango2 immediately.
# The saved snippet keeps the notify and drops the EAP identity, secret, and ESP key.
cat > "$tmp/initiate-generic.txt" << 'EOF'
initiate failed: establishing CHILD_SA 'mango' failed
EOF
cat > "$tmp/charon-append.txt" << 'EOF'
[IKE] received EAP identity 'alice@example.com'
[IKE] IDi 'alice@example.com'
secret = "s3cr3t-value"
encryption key => aabbccddeeff00112233445566778899
00 11 22 33 44 55 66 77 88 99 aa bb cc dd ee ff
[IKE] received INTERNAL_ADDRESS_FAILURE notify, no CHILD_SA built
[IKE] establishing connection 'mango' failed
EOF
cat > "$tmp/child-missing.sas" << 'EOF'
mango: #4, ESTABLISHED, IKEv2, aaaa_i* bbbb_r
  local  'vpn-user' @ 192.0.2.10[4500] [10.7.0.8]
  remote 'nordvpn' @ 203.0.113.5[4500]
  AES_CBC-256/HMAC_SHA2_256_128/PRF_HMAC_SHA2_256/ECP_256
  established 20s ago, rekeying in 3000s
EOF
cat > "$tmp/mango2-up.sas" << 'EOF'
mango2: #8, ESTABLISHED, IKEv2, cccc_i* dddd_r
  local  'vpn-user' @ 192.0.2.10[4500] [10.8.0.4]
  remote 'backup.example' @ 203.0.113.9[4500]
  AES_CBC-256/HMAC_SHA2_256_128/PRF_HMAC_SHA2_256/ECP_256
  established 1s ago, rekeying in 3000s
  mango2: #3, reqid 1, INSTALLED, TUNNEL, ESP:AES_GCM_16-256
    installed 1s ago, rekeying in 1000s, expires in 2000s
    in  a1b2c3d4, 0 bytes, 0 packets
    out e5f6a7b8, 0 bytes, 0 packets
    local  10.8.0.4/32
    remote 0.0.0.0/0
EOF
cp "$tmp/child-missing.sas" "$SAS_FILE"
rm -f "$SWANCTL_DOWN"
unset IP_ADDR_SHOW UCI_SERVER3 || true
SAS_AFTER_INITIATE=$tmp/mango2-up.sas
IAF_PEERS=mango
UCI_SERVER2=backup.example
INITIATE_CHARON_APPEND_FILE=$tmp/charon-append.txt
export SAS_AFTER_INITIATE IAF_PEERS UCI_SERVER2 INITIATE_CHARON_APPEND_FILE
unset INITIATE_STDERR_FILE || true
: > "$MANGO_IKEV2_CHARON_LOG"
: > "$MANGO_IKEV2_SNIP"
printf '%s\n' mango > "$tmp/state/active"
printf '%s\n' 1 > "$tmp/state/fail-count"
printf '%s\n' 0 > "$tmp/state/fallback-fail"
printf '%s\n' mango > "$tmp/state/int-addr-round"
reset_logs
run_failover
test "$(cat "$tmp/state/active")" = mango2
test "$(cat "$tmp/state/fail-count")" = 0
test "$(cat "$tmp/state/fallback-fail")" = 0
test ! -f "$tmp/state/int-addr-until"
test ! -f "$tmp/state/int-addr-round"
test "$(grep -c -- '--child mango --timeout' "$SWANCTL_LOG")" = 1
test "$(grep -c -- '--child mango2 --timeout' "$SWANCTL_LOG")" = 1
awk '
	index($0, "--initiate --child mango ") { child = NR }
	index($0, "--terminate") && !term { term = NR }
	index($0, "--initiate --ike mango2 ") { nextp = NR }
	END {
		if (!(child && term && nextp && child < term && term < nextp)) exit 1
	}
' "$SWANCTL_LOG" || {
	printf '%s\n' 'IAF did not terminate the live SA before dialing mango2' >&2
	cat "$SWANCTL_LOG" >&2
	exit 1
}
grep -q INTERNAL_ADDRESS_FAILURE "$MANGO_IKEV2_SNIP"
if grep -q 'alice@example.com' "$MANGO_IKEV2_SNIP" || grep -q 's3cr3t-value' "$MANGO_IKEV2_SNIP" || grep -q 'aabbccddeeff00112233445566778899' "$MANGO_IKEV2_SNIP" || grep -q '00 11 22' "$MANGO_IKEV2_SNIP"; then
	printf '%s\n' 'charon snippet kept credentials or key material' >&2
	cat "$MANGO_IKEV2_SNIP" >&2
	exit 1
fi

# Every configured peer returns IAF: one backoff, then the next dial is the primary.
cat > "$tmp/primary-up.sas" << 'EOF'
mango: #1, ESTABLISHED, IKEv2
  local 192.0.2.1[10.5.0.2]
  remote vpn.example[203.0.113.5]
  mango: #1, INSTALLED, TUNNEL
    local  10.5.0.2/32
    remote 0.0.0.0/0
EOF
: > "$SAS_FILE"
rm -f "$SWANCTL_DOWN" "$tmp/state/int-addr-until" "$tmp/state/int-addr-round"
unset SAS_AFTER_INITIATE INITIATE_CHARON_APPEND_FILE INITIATE_STDERR_FILE || true
IAF_PEERS='mango mango2 mango3'
UCI_SERVER2=backup.example
UCI_SERVER3=backup3.example
export IAF_PEERS UCI_SERVER2 UCI_SERVER3
: > "$MANGO_IKEV2_CHARON_LOG"
printf '%s\n' mango > "$tmp/state/active"
printf '%s\n' 0 > "$tmp/state/fail-count"
printf '%s\n' 0 > "$tmp/state/fallback-fail"
reset_logs
run_failover
test "$(cat "$tmp/state/active")" = mango
test "$(cat "$tmp/state/fail-count")" = 0
test "$(cat "$tmp/state/fallback-fail")" = 0
test ! -f "$tmp/state/int-addr-round"
test "$(grep -c -- '--child mango --timeout' "$SWANCTL_LOG")" = 1
test "$(grep -c -- '--child mango2 --timeout' "$SWANCTL_LOG")" = 1
test "$(grep -c -- '--child mango3 --timeout' "$SWANCTL_LOG")" = 1
until=$(cat "$tmp/state/int-addr-until")
now=$(date +%s)
test "$((until - now))" -ge 30
test "$((until - now))" -le 60
reset_logs
run_failover
if grep -q -- '--initiate' "$SWANCTL_LOG"; then
	printf '%s\n' 'backoff tick dialed again' >&2
	cat "$SWANCTL_LOG" >&2
	exit 1
fi
rm -f "$tmp/state/int-addr-until"
unset IAF_PEERS || true
SAS_AFTER_INITIATE=$tmp/primary-up.sas
export SAS_AFTER_INITIATE
reset_logs
run_failover
test "$(grep -c -- '--child mango --timeout' "$SWANCTL_LOG")" = 1
if grep -q -- '--child mango2 --timeout' "$SWANCTL_LOG" || grep -q -- '--child mango3 --timeout' "$SWANCTL_LOG"; then
	printf '%s\n' 'post-backoff retry did not start at the primary' >&2
	cat "$SWANCTL_LOG" >&2
	exit 1
fi
test "$(cat "$tmp/state/active")" = mango
test ! -f "$tmp/state/int-addr-round"

# A normal dial failure still switches after the second miss and clears IAF tracking.
unset SAS_AFTER_INITIATE UCI_SERVER3 IAF_PEERS || true
INITIATE_STDERR_FILE=$tmp/initiate-generic.txt
export INITIATE_STDERR_FILE
UCI_SERVER2=backup.example
export UCI_SERVER2
: > "$SAS_FILE"
rm -f "$SWANCTL_DOWN" "$tmp/state/int-addr-until"
: > "$MANGO_IKEV2_CHARON_LOG"
printf '%s\n' mango > "$tmp/state/int-addr-round"
printf '%s\n' 1 > "$tmp/state/fail-count"
printf '%s\n' 0 > "$tmp/state/fallback-fail"
printf '%s\n' mango > "$tmp/state/active"
reset_logs
run_failover
grep -q -- '--ike mango2' "$SWANCTL_LOG"
test "$(cat "$tmp/state/active")" = mango2
test "$(cat "$tmp/state/fallback-fail")" = 2
test ! -f "$tmp/state/int-addr-round"

# A second failover overlaps a dial that can take 15s. The lock must skip it.
unset UCI_SERVER2 UCI_SERVER3 INITIATE_STDERR_FILE IAF_PEERS || true
# Empty listing would flush and initiate if the lock did not hold.
: > "$SAS_FILE"
printf '%s\n' mango > "$tmp/state/active"
printf '%s\n' 0 > "$tmp/state/fail-count"
held=$tmp/held.lock
flock -n "$held" -c 'sleep 30' &
holder=$!
sleep 0.2
if flock -n "$held" -c true 2>/dev/null; then
	printf '%s\n' 'overlap lock was not acquired' >&2
	kill "$holder" 2>/dev/null || true
	wait "$holder" 2>/dev/null || true
	exit 1
fi
reset_logs
set +e
MANGO_IKEV2_LOCK=$held MANGO_IKEV2_LOCK_WAIT=0 \
	PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state \
	sh "$script" >/dev/null 2>"$tmp/overlap.err"
overlap_rc=$?
set -e
kill "$holder" 2>/dev/null || true
wait "$holder" 2>/dev/null || true
test "$overlap_rc" = 0
if [ -s "$SWANCTL_LOG" ] || grep -q -- '-4 addr flush' "$IP_LOG"; then
	printf '%s\n' 'overlapping failover ran while the lock was held' >&2
	cat "$SWANCTL_LOG" "$IP_LOG" >&2
	exit 1
fi
test "$(cat "$tmp/state/fail-count")" = 0

# Event log keeps 200 lines, not 20.
event_log=$tmp/events.log
n=1
while [ "$n" -le 210 ]; do
	MANGO_IKEV2_EVENT_LOG=$event_log PATH="$tmp/bin:$PATH" \
		sh "$log_script" fail mango "n=$n" >/dev/null
	n=$((n + 1))
done
test "$(wc -l < "$event_log" | tr -d ' ')" = 200
head -n 1 "$event_log" | grep -q 'n=11'
tail -n 1 "$event_log" | grep -q 'n=210'

python3 - "$script" "$log_script" << 'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
log = Path(sys.argv[2]).read_text()
assert text.count("clear_vip") == 3, text.count("clear_vip")
assert "prepare_dial() {\n\tclear_vip\n" in text
assert "if any_ike_sa; then\n\t\treturn 0\n\tfi\n\tif ip link show" in text
dead = text.index('log_event fail "$active" "datapath dead; redial"')
skip = text.index('SA still present after terminate; skip redial', dead)
assert "reset_datapath_fail" not in text[dead:skip]
cleared = text.index("\treset_datapath_fail\n\tclear_vip\n", skip)
assert cleared > skip
start = text.index("\tvip=$(peer_vip \"$active\")\n\tsync_vip \"$vip\"\n\tensure_dns_routes\n\tif datapath_ok; then\n")
end = text.index("\tfi\n\t# SA looks fine but tunnel probe failed", start)
healthy = text[start:end]
assert "clear_vip" not in healthy
assert "sync_vip" in healthy
assert "ensure_dns_routes" in healthy
assert "http_probe https://www.gstatic.com/generate_204" in text
assert "http_probe https://www.google.com/generate_204" in text
assert 'datapath probe failed (#$n/3); keep SA' in text
assert '[ "$n" -lt 3 ]' in text
assert "REKEYING|REKEYED|DELETING" in text
assert "MANGO_IKEV2_POST_TERM_WAIT:-15" in text
assert "MANGO_IKEV2_INT_ADDR_BACKOFF:-45" in text
assert "flock -w" in text
assert "INTERNAL_ADDRESS_FAILURE; all peers; backoff" in text
assert "iaf_round_complete" in text
assert "swanctl --initiate --child" in text
assert "tail -n 200" in log
print("healthy recheck keeps the VIP; rekey overlap does not flush; IAF rotates peers")
PY
