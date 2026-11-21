#!/bin/sh
# A CONNECTING IKE SA is not skipped forever. After CONNECTING_GRACE the
# leftover SA is terminated and counted. Two failures switch to the next server.
# A failed initiate also terminates a leftover CONNECTING SA.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
script=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-failover
sh -n "$script"
sh -n "$root/tr3600/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2"
tmp=$(mktemp -d)
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT
mkdir -p "$tmp/bin" "$tmp/state" "$tmp/swanctl"
now=$(cut -d. -f1 /proc/uptime)

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
	mango_ikev2.main.server3) exit 1 ;;
	mango_ikev2.main.ssr_fallback) printf '%s\n' 0 ;;
	mango_ikev2.main.ssr_fallback_fails) printf '%s\n' 6 ;;
	*) exit 1 ;;
esac
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
		touch "${SWANCTL_DOWN:?}"
		exit 0
		;;
	--initiate)
		if [ -n "${INITIATE_FAIL:-}" ]; then
			echo 'initiate failed' >&2
			exit 1
		fi
		rm -f "${SWANCTL_DOWN:-}"
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
	"link show xfrm-mango") exit 0 ;;
	"link set xfrm-mango mtu 1280 up") exit 0 ;;
esac
exit 0
EOF
cat > "$tmp/bin/generate" << 'EOF'
#!/bin/sh
printf '%s\n' '# swanctl'
exit 0
EOF
cat > "$tmp/bin/fw" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/bin/event-log" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${EVENT_LOG:?}"
EOF
cat > "$tmp/sas-connecting" << 'EOF'
mango: #2, CONNECTING, IKEv2, aaaa_i bbbb_r
  local  'vpn-user' @ 192.0.2.10[500]
  remote 'vpn.example' @ 203.0.113.9[500]
EOF
chmod 755 "$tmp/bin/uci" "$tmp/bin/swanctl" "$tmp/bin/ip" "$tmp/bin/generate" "$tmp/bin/fw" "$tmp/bin/event-log"
printf '%s\n' mango > "$tmp/state/active"
printf '%s\n' 0 > "$tmp/state/fail-count"
printf '%s\n' 0 > "$tmp/state/fallback-fail"
cp "$tmp/sas-connecting" "$tmp/sas"
: > "$tmp/swanctl.log"
: > "$tmp/events.log"
: > "$tmp/ip.log"
export SWANCTL_LOG=$tmp/swanctl.log SAS_FILE=$tmp/sas SWANCTL_DOWN=$tmp/swan-down
export IP_LOG=$tmp/ip.log EVENT_LOG=$tmp/events.log
export MANGO_IKEV2_LOG=$tmp/bin/event-log
export MANGO_IKEV2_LOCK=$tmp/lock MANGO_IKEV2_LOCK_WAIT=2
export MANGO_IKEV2_LIFECYCLE=$root/tr3600/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/lifecycle.sh
export MANGO_IKEV2_GENERATE=$tmp/bin/generate
export MANGO_IKEV2_FW=$tmp/bin/fw
export MANGO_IKEV2_SWANCTL_DIR=$tmp/swanctl
export MANGO_IKEV2_POST_TERM_WAIT=0 MANGO_IKEV2_SA_POLL=0
export MANGO_IKEV2_CHARON_LOG=$tmp/charon.log MANGO_IKEV2_SNIP=$tmp/snip
: > "$tmp/charon.log"
export MANGO_IKEV2_STATE=$tmp/state
export MANGO_IKEV2_CONNECTING_GRACE=60
unset UCI_SERVER2 INITIATE_FAIL || true

run() {
	: > "$tmp/swanctl.log"
	PATH="$tmp/bin:$PATH" sh "$script" >/dev/null 2>"$tmp/run.err"
}

# Inside the grace window the watchdog waits and does not terminate.
rm -f "$tmp/swan-down" "$tmp/state/connecting-mango"
run
test ! -f "$tmp/swan-down"
test -s "$tmp/state/connecting-mango"
if grep -q -- '--terminate' "$tmp/swanctl.log"; then
	echo 'grace tick terminated a fresh CONNECTING SA' >&2
	exit 1
fi
test "$(cat "$tmp/state/fail-count")" = 0

# Grace expired: terminate and count one failure. One server, so no switch.
rm -f "$tmp/swan-down"
cp "$tmp/sas-connecting" "$tmp/sas"
echo $((now - 120)) > "$tmp/state/connecting-mango"
run
test -f "$tmp/swan-down"
grep -q -- '--terminate --ike mango --timeout 3' "$tmp/swanctl.log"
grep -q 'CONNECTING grace expired (60s)' "$tmp/events.log"
test "$(cat "$tmp/state/fail-count")" = 1
test "$(cat "$tmp/state/active")" = mango
test ! -f "$tmp/state/connecting-mango"
if grep -q -- '--load-conns --noprompt' "$tmp/swanctl.log"; then
	echo 'load-conns still passes --noprompt' >&2
	exit 1
fi

# A second counted failure switches to backup 1.
UCI_SERVER2=backup.example
export UCI_SERVER2
rm -f "$tmp/swan-down"
cp "$tmp/sas-connecting" "$tmp/sas"
echo $((now - 120)) > "$tmp/state/connecting-mango"
printf '%s\n' 1 > "$tmp/state/fail-count"
run
grep -q '节点切换 主服务器 → 备用服务器1' "$tmp/events.log"
test "$(cat "$tmp/state/active")" = mango2

# A failed initiate clears the leftover CONNECTING SA.
unset UCI_SERVER2 || true
rm -f "$tmp/swan-down" "$tmp/state/connecting-mango"
: > "$tmp/sas"
printf '%s\n' 0 > "$tmp/state/fail-count"
printf '%s\n' mango > "$tmp/state/active"
INITIATE_FAIL=1
export INITIATE_FAIL
run
grep -q -- '--initiate' "$tmp/swanctl.log"
grep -q -- '--terminate --ike mango --timeout 3' "$tmp/swanctl.log"
unset INITIATE_FAIL

echo "CONNECTING grace counts a stuck dial and the second failure switches servers"
