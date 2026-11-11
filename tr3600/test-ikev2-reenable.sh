#!/bin/sh
# After SSR fallback, enabled=0 must not be treated as a start.
# Once enabled=1 is what apply reads, claim SSR and bring the tunnel up.
# The generic config.change hook must reload mango_ikev2 when ucitrack is absent.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
init=$root/tr3600/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2
hook=$root/tr3600/luci-app-mango-ikev2/root/etc/init.d/mango-ikev2-track
defaults=$root/tr3600/luci-app-mango-ikev2/root/etc/uci-defaults/95-mango-ikev2
life=$root/tr3600/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/lifecycle.sh
tmp=$(mktemp -d)
cleanup() {
	if [ -n "${watch_pid:-}" ]; then
		kill "$watch_pid" 2>/dev/null || true
		wait "$watch_pid" 2>/dev/null || true
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
		printf '%s\n' 'dhcp.lan=dnsmasq'
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
	commit)
		;;
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
printf '%s\n' fw >> "${FW_LOG:?}"
exit 0
EOF
cat > "$tmp/bin/swanctl" << 'EOF'
#!/bin/sh
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
printf '%s\n' started >> "${WATCH_LOG:?}"
sleep 60
EOF
cat > "$tmp/bin/failover" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/init/dnsmasq" << 'EOF'
#!/bin/sh
exit 0
EOF
chmod 755 "$tmp/bin/"* "$tmp/init/dnsmasq"
python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.listen(1)' "$tmp/vici"

printf '%s\n' 0 > "$tmp/uci/values/mango_ikev2.main.enabled"
printf '%s\n' split > "$tmp/uci/values/mango_ikev2.main.mode"
printf '%s\n' cidrs > "$tmp/etc/cn-cidrs.txt"
: > "$tmp/peer.log"
: > "$tmp/fw.log"
: > "$tmp/ip.log"
: > "$tmp/watch.log"

export UCI_DIR=$tmp/uci \
	PEER_LOG=$tmp/peer.log \
	FW_LOG=$tmp/fw.log \
	IP_LOG=$tmp/ip.log \
	WATCH_LOG=$tmp/watch.log \
	XFRM_UP=$tmp/xfrm-up \
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
	PATH="$tmp/bin:$PATH"
extra_command() { :; }
# shellcheck disable=SC1090
. "$init"

# Fallback-like state: enabled is still 0. Apply tears down and does not claim.
mango_ikev2_apply
test "$(cat "$tmp/peer.log")" = release
test ! -f "$tmp/xfrm-up"
test ! -f "$tmp/watch.pid"
test ! -f "$tmp/state/swanctl.conf"

# The committed value is now 1. The same reload must claim and build the path.
printf '%s\n' 1 > "$tmp/uci/values/mango_ikev2.main.enabled"
: > "$tmp/peer.log"
: > "$tmp/fw.log"
: > "$tmp/ip.log"
mango_ikev2_apply
test "$(cat "$tmp/peer.log")" = claim
test -f "$tmp/xfrm-up"
grep -q 'link add xfrm-mango type xfrm dev eth0 if_id 42' "$tmp/ip.log"
test "$(cat "$tmp/fw.log")" = fw
test -s "$tmp/state/swanctl.conf"
test "$(cat "$tmp/watch.log")" = started
test -s "$tmp/watch.pid"
watch_pid=$(cat "$tmp/watch.pid")

# Generic apply hook: no ucitrack means config.change reloads this init.
grep -q 'procd_add_config_trigger "config.change" "mango_ikev2"' "$hook"
grep -q '/etc/init.d/mango_ikev2 reload' "$hook"
grep -q 'mango-ikev2-track enable' "$defaults"
grep -q 'USE_PROCD=1' "$hook"
if ! grep -q '^USE_PROCD=1' "$init"; then
	:
else
	printf '%s\n' 'mango_ikev2 must stay non-procd so ucitrack can hook it' >&2
	exit 1
fi
procd_add_config_trigger() {
	printf '%s\n' "$*" > "$tmp/trig"
}
# shellcheck disable=SC1090
. "$hook"
service_triggers
if [ -x /etc/init.d/ucitrack ]; then
	test ! -s "$tmp/trig"
else
	test "$(cat "$tmp/trig")" = 'config.change mango_ikev2 /etc/init.d/mango_ikev2 reload'
fi

echo "re-enable claims SSR and starts the tunnel; config.change reloads IKEv2"
