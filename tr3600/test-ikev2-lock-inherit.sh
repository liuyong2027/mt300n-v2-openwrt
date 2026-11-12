#!/bin/sh
# The watchdog must not inherit the lifecycle lock. stop and SSR yield
# have to tear a live tunnel down without waiting out the 120s flock.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
init=$root/tr3600/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2
engine=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-peer-engine
life=$root/tr3600/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/lifecycle.sh
tmp=$(mktemp -d)
watch_pid=
child_pid=
cleanup() {
	if [ -n "${watch_pid:-}" ]; then
		kill "$watch_pid" 2>/dev/null || true
		wait "$watch_pid" 2>/dev/null || true
	fi
	if [ -n "${child_pid:-}" ]; then
		kill "$child_pid" 2>/dev/null || true
		wait "$child_pid" 2>/dev/null || true
	fi
	rm -rf "$tmp"
}
trap cleanup EXIT
mkdir -p "$tmp/bin" "$tmp/etc" "$tmp/state" "$tmp/swanctl" "$tmp/uci/values" "$tmp/init"

cat > "$tmp/bin/uci" << 'EOF'
#!/bin/sh
state=${UCI_DIR:?}
action=$1
shift
if [ "$action" = -q ]; then
	action=$1
	shift
fi
mkdir -p "$state/values"
case "$action" in
	show)
		case "${1-}" in
			shadowsocksr)
				printf '%s\n' 'shadowsocksr.global=global'
				;;
			*)
				printf '%s\n' 'dhcp.lan=dnsmasq'
				;;
		esac
		;;
	get)
		key=$1
		if [ -f "$state/values/$key" ]; then
			cat "$state/values/$key"
			exit 0
		fi
		exit 1
		;;
	set)
		key=${1%%=*}
		val=${1#*=}
		printf '%s\n' "$val" > "$state/values/$key"
		;;
	delete)
		rm -f "$state/values/$1"
		;;
	add_list)
		key=${1%%=*}
		val=${1#*=}
		printf '%s\n' "$val" >> "$state/values/$key"
		;;
	commit) ;;
	*) exit 1 ;;
esac
EOF
cat > "$tmp/bin/peer" << 'EOF'
#!/bin/sh
printf '%s\n' "$1" >> "${PEER_LOG:?}"
exit 0
EOF
cat > "$tmp/bin/generate" << 'EOF'
#!/bin/sh
printf '%s\n' "# $1"
exit 0
EOF
cat > "$tmp/bin/fw" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/bin/swanctl" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${SWANCTL_LOG:?}"
exit 0
EOF
cat > "$tmp/bin/ip" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${IP_LOG:?}"
case "$*" in
	"link show xfrm-mango")
		[ -f "${XFRM_UP:?}" ] || exit 1
		;;
	"link add xfrm-mango type xfrm dev eth0 if_id 42")
		touch "$XFRM_UP"
		;;
	"link del xfrm-mango")
		rm -f "$XFRM_UP"
		;;
	"link set xfrm-mango mtu 1280 up")
		[ -f "$XFRM_UP" ] || exit 1
		;;
esac
exit 0
EOF
cat > "$tmp/bin/pidof" << 'EOF'
#!/bin/sh
[ "$1" = charon ]
EOF
cat > "$tmp/bin/watch" << 'EOF'
#!/bin/sh
state=clean
if [ "${MANGO_IKEV2_LOCK_HELD:-}" = 1 ]; then
	state=held
fi
if ( : >&9 ) 2>/dev/null; then
	state="${state}+fd9"
fi
printf '%s\n' "$state" > "${WATCH_STATE:?}"
sh -c 'if ( : >&9 ) 2>/dev/null; then echo fd9; else echo clean; fi > "$1"; sleep 120' sh "${CHILD_STATE:?}" &
child=$!
printf '%s\n' "$child" > "${SLEEP_PID:?}"
trap 'kill "$child" 2>/dev/null || true; exit 0' TERM INT
wait "$child"
EOF
cat > "$tmp/bin/failover" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/init/dnsmasq" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/init/mango_ikev2" << 'EOF'
#!/bin/sh
export MANGO_IKEV2_LOCK_WAIT=1
extra_command() { :; }
# shellcheck disable=SC1090
. "$INIT_SRC"
stop
EOF
chmod 755 "$tmp/bin/"* "$tmp/init/dnsmasq" "$tmp/init/mango_ikev2"
python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.listen(1)' "$tmp/vici"

printf '%s\n' 0 > "$tmp/uci/values/mango_ikev2.main.enabled"
printf '%s\n' split > "$tmp/uci/values/mango_ikev2.main.mode"
printf '%s\n' node1 > "$tmp/uci/values/shadowsocksr.global.global_server"
printf '%s\n' cidrs > "$tmp/etc/cn-cidrs.txt"
: > "$tmp/peer.log"
: > "$tmp/ip.log"
: > "$tmp/swanctl.log"

export UCI_DIR=$tmp/uci \
	PEER_LOG=$tmp/peer.log \
	IP_LOG=$tmp/ip.log \
	SWANCTL_LOG=$tmp/swanctl.log \
	WATCH_STATE=$tmp/watch-state \
	CHILD_STATE=$tmp/child-state \
	SLEEP_PID=$tmp/sleep.pid \
	XFRM_UP=$tmp/xfrm-up \
	INIT_SRC=$init \
	MANGO_IKEV2_STATE=$tmp/state \
	MANGO_IKEV2_ETC=$tmp/etc \
	MANGO_IKEV2_DNSMASQ_INIT=$tmp/init/dnsmasq \
	MANGO_IKEV2_LIFECYCLE=$life \
	MANGO_IKEV2_GENERATE=$tmp/bin/generate \
	MANGO_IKEV2_PEER_ENGINE=$tmp/bin/peer \
	MANGO_IKEV2_FW=$tmp/bin/fw \
	MANGO_IKEV2_FAILOVER=$tmp/bin/failover \
	MANGO_IKEV2_WATCH=$tmp/bin/watch \
	MANGO_IKEV2_WATCH_PID=$tmp/watch.pid \
	MANGO_IKEV2_LOCK=$tmp/lock \
	MANGO_IKEV2_SWANCTL_DIR=$tmp/swanctl \
	MANGO_IKEV2_VICI=$tmp/vici \
	MANGO_IKEV2_LOCK_WAIT=5 \
	MANGO_IKEV2_INIT=$tmp/init/mango_ikev2 \
	PATH="$tmp/bin:$PATH"

apply_detached() {
	# Match /etc/init.d: the lock fd dies with the apply process.
	(
		extra_command() { :; }
		# shellcheck disable=SC1090
		. "$init"
		mango_ikev2_apply
	)
}

wait_file() {
	i=0
	while [ ! -s "$1" ] && [ "$i" -lt 50 ]; do
		sleep 0.1
		i=$((i + 1))
	done
	test -s "$1"
}

# enabled=0 tears down and does not claim.
apply_detached
test "$(cat "$tmp/peer.log")" = release
test ! -f "$tmp/xfrm-up"
test ! -f "$tmp/watch.pid"

# enabled=1 builds the tunnel. The watchdog must not keep the lock.
printf '%s\n' 1 > "$tmp/uci/values/mango_ikev2.main.enabled"
: > "$tmp/peer.log"
rm -f "$tmp/watch-state" "$tmp/child-state" "$tmp/sleep.pid" "$tmp/watch.pid"
apply_detached
test "$(cat "$tmp/peer.log")" = claim
test -f "$tmp/xfrm-up"
wait_file "$tmp/watch-state"
wait_file "$tmp/child-state"
wait_file "$tmp/sleep.pid"
test "$(cat "$tmp/watch-state")" = clean
test "$(cat "$tmp/child-state")" = clean
watch_pid=$(cat "$tmp/watch.pid")
child_pid=$(cat "$tmp/sleep.pid")
kill -0 "$watch_pid"
kill -0 "$child_pid"
if ! flock -w 1 "$tmp/lock" -c true; then
	printf '%s\n' 'watchdog kept the lifecycle lock after apply' >&2
	exit 1
fi

# stop acquires the lock at once and removes the tunnel and the watchdog.
: > "$tmp/ip.log"
: > "$tmp/swanctl.log"
: > "$tmp/peer.log"
sh "$tmp/init/mango_ikev2" stop
if kill -0 "$watch_pid" 2>/dev/null; then
	printf '%s\n' 'stop left the watchdog running' >&2
	exit 1
fi
if kill -0 "$child_pid" 2>/dev/null; then
	printf '%s\n' 'stop left the watchdog sleep child running' >&2
	exit 1
fi
watch_pid=
child_pid=
grep -q 'link del xfrm-mango' "$tmp/ip.log"
grep -q -- '--terminate --ike mango' "$tmp/swanctl.log"
test ! -f "$tmp/xfrm-up"
test "$(cat "$tmp/peer.log")" = release
if ! flock -w 1 "$tmp/lock" -c true; then
	printf '%s\n' 'stop left the lifecycle lock held' >&2
	exit 1
fi

# Bring IKEv2 back, then SSR yield must stop it instead of timing out.
printf '%s\n' 1 > "$tmp/uci/values/mango_ikev2.main.enabled"
printf '%s\n' node1 > "$tmp/uci/values/shadowsocksr.global.global_server"
: > "$tmp/peer.log"
: > "$tmp/ip.log"
: > "$tmp/swanctl.log"
rm -f "$tmp/watch-state" "$tmp/child-state" "$tmp/sleep.pid" "$tmp/watch.pid"
apply_detached
wait_file "$tmp/watch-state"
test "$(cat "$tmp/watch-state")" = clean
test "$(cat "$tmp/peer.log")" = claim
watch_pid=$(cat "$tmp/watch.pid")
child_pid=$(cat "$tmp/sleep.pid")
if ! flock -w 1 "$tmp/lock" -c true; then
	printf '%s\n' 'second watchdog kept the lifecycle lock' >&2
	exit 1
fi
: > "$tmp/ip.log"
: > "$tmp/swanctl.log"
PATH="$tmp/bin:$PATH" sh "$engine" yield
test "$(cat "$tmp/uci/values/mango_ikev2.main.enabled")" = 0
if kill -0 "$watch_pid" 2>/dev/null; then
	printf '%s\n' 'SSR yield left the watchdog running' >&2
	exit 1
fi
if kill -0 "$child_pid" 2>/dev/null; then
	printf '%s\n' 'SSR yield left the watchdog sleep child running' >&2
	exit 1
fi
watch_pid=
child_pid=
grep -q 'link del xfrm-mango' "$tmp/ip.log"
grep -q -- '--terminate --ike mango' "$tmp/swanctl.log"
test ! -f "$tmp/xfrm-up"
test "$(cat "$tmp/uci/values/shadowsocksr.global.global_server")" = node1

echo "watchdog drops the lifecycle lock; stop and SSR yield tear the tunnel down"
