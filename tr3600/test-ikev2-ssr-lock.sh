#!/bin/sh
# SSR started from failover must not inherit the lifecycle lock on fd 9.
# Manual re-enable has to be able to take that lock again.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
engine=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-peer-engine
fallback=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-fallback-ssr
sh -n "$engine"
sh -n "$fallback"
tmp=$(mktemp -d)
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT
mkdir -p "$tmp/bin" "$tmp/init" "$tmp/uci/values" "$tmp/uci/nodes" "$tmp/state"

cat > "$tmp/bin/uci" << 'EOF'
#!/bin/sh
state=${UCI_DIR:?}
action=$1
shift
if [ "$action" = -q ]; then
	action=$1
	shift
fi
case "$action" in
	show)
		if [ "${1-}" = shadowsocksr ]; then
			printf '%s\n' 'shadowsocksr.global=global'
		fi
		;;
	get)
		key=$1
		if [ -f "$state/values/$key" ]; then
			cat "$state/values/$key"
			exit 0
		fi
		case "$key" in
			shadowsocksr.node1) printf '%s\n' servers; exit 0 ;;
		esac
		exit 1
		;;
	set)
		key=${1%%=*}
		val=${1#*=}
		mkdir -p "$state/values"
		printf '%s\n' "$val" > "$state/values/$key"
		;;
	commit) ;;
	*) exit 1 ;;
esac
EOF
cat > "$tmp/init/shadowsocksr" << 'EOF'
#!/bin/sh
if [ -e /proc/self/fd/9 ]; then
	printf '%s\n' open > "${FD_LOG:?}"
else
	printf '%s\n' closed > "${FD_LOG:?}"
fi
printf '%s\n' "held=${MANGO_IKEV2_LOCK_HELD-unset}" >> "${FD_LOG:?}"
printf '%s\n' "$*" >> "${CALL_LOG:?}"
# A daemon that would keep an inherited lock must not see fd 9 either.
if [ -e /proc/self/fd/9 ]; then
	printf '%s\n' 'child-open' >> "${FD_LOG:?}"
else
	printf '%s\n' 'child-closed' >> "${FD_LOG:?}"
fi
exit 0
EOF
cat > "$tmp/init/mango_ikev2" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${CALL_LOG:?}"
exit 0
EOF
cat > "$tmp/bin/ike-log" << 'EOF'
#!/bin/sh
exit 0
EOF
# The image build marks shebang helpers executable. Host copies need the
# same bit, because fallback runs the peer engine directly.
cp "$engine" "$tmp/bin/peer-engine"
cp "$fallback" "$tmp/bin/fallback"
chmod 755 "$tmp/bin/uci" "$tmp/init/shadowsocksr" "$tmp/init/mango_ikev2" "$tmp/bin/ike-log" "$tmp/bin/peer-engine" "$tmp/bin/fallback"
engine=$tmp/bin/peer-engine
fallback=$tmp/bin/fallback
touch "$tmp/uci/nodes/node1"
printf '%s\n' node1 > "$tmp/ssr-prev"
printf '%s\n' nil > "$tmp/uci/values/shadowsocksr.global.global_server"
printf '%s\n' 1 > "$tmp/uci/values/mango_ikev2.main.enabled"
printf '%s\n' 1 > "$tmp/uci/values/mango_ikev2.main.ssr_fallback"
printf '%s\n' 4 > "$tmp/state/fallback-fail"
: > "$tmp/calls"
: > "$tmp/fd"
export UCI_DIR=$tmp/uci
export FD_LOG=$tmp/fd CALL_LOG=$tmp/calls
export MANGO_IKEV2_SSR_PREV=$tmp/ssr-prev
export SSR_INIT=$tmp/init/shadowsocksr
export MANGO_IKEV2_INIT=$tmp/init/mango_ikev2
export MANGO_IKEV2_LOG=$tmp/bin/ike-log
export MANGO_IKEV2_STATE=$tmp/state
export MANGO_IKEV2_FALLBACK_LOCK=$tmp/fallback.lock
export MANGO_IKEV2_PEER_ENGINE=$engine
PATH="$tmp/bin:$PATH"

# Direct restore while this shell holds the lifecycle lock.
exec 9>"$tmp/lifecycle.lock"
export MANGO_IKEV2_LOCK_HELD=1
PATH="$tmp/bin:$PATH" sh "$engine" restore
test "$(head -n 1 "$tmp/fd")" = closed
grep -qx 'held=unset' "$tmp/fd"
grep -qx 'child-closed' "$tmp/fd"
test "$(cat "$tmp/uci/values/mango_ikev2.main.enabled")" = 1

# Fallback still disables IKEv2, and the SSR restart it starts also has fd 9 closed.
: > "$tmp/fd"
: > "$tmp/calls"
PATH="$tmp/bin:$PATH" sh "$fallback"
test "$(cat "$tmp/uci/values/mango_ikev2.main.enabled")" = 0
test "$(head -n 1 "$tmp/fd")" = closed
grep -qx 'held=unset' "$tmp/fd"
# The parent still holds fd 9, so a later manual IKEv2 restart can take the lock.
if ! flock -n 9; then
	echo 'lifecycle lock stayed busy after SSR restore' >&2
	exit 1
fi

echo "SSR restart does not inherit the IKEv2 lifecycle lock"
