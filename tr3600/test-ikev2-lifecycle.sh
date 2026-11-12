#!/bin/sh
# Lifecycle lock, DNS teardown, and WAN source address.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
life=$root/tr3600/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/lifecycle.sh
init=$root/tr3600/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2
wan=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-wan-addr
tmp=$(mktemp -d)
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT
mkdir -p "$tmp/bin" "$tmp/etc/dnsmasq.d" "$tmp/init" "$tmp/uci/values"

# Nested stop must not try to take the lock again.
# shellcheck disable=SC1090
. "$life"
lock=$tmp/life.lock
flock -n "$lock" -c 'sleep 30' &
holder=$!
sleep 0.2
if MANGO_IKEV2_LOCK=$lock MANGO_IKEV2_LOCK_WAIT=0 mango_ikev2_lifecycle_enter; then
	printf '%s\n' 'lifecycle lock was not exclusive' >&2
	kill "$holder" 2>/dev/null || true
	exit 1
fi
MANGO_IKEV2_LOCK_HELD=1
MANGO_IKEV2_LOCK=$lock MANGO_IKEV2_LOCK_WAIT=0 mango_ikev2_lifecycle_enter
kill "$holder" 2>/dev/null || true
wait "$holder" 2>/dev/null || true
unset MANGO_IKEV2_LOCK_HELD

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
		printf 'commit %s\n' "$1" >> "$state/log"
		;;
	*) exit 1 ;;
esac
EOF
cat > "$tmp/init/dnsmasq" << 'EOF'
#!/bin/sh
printf 'dnsmasq %s\n' "$1" >> "${DNSMASQ_LOG:?}"
EOF
chmod 755 "$tmp/bin/uci" "$tmp/init/dnsmasq"
UCI_DIR=$tmp/uci
DNSMASQ_LOG=$tmp/dnsmasq.log
export UCI_DIR DNSMASQ_LOG PATH="$tmp/bin:$PATH"
export MANGO_IKEV2_ETC=$tmp/etc
export MANGO_IKEV2_DNSMASQ_INIT=$tmp/init/dnsmasq
export MANGO_IKEV2_LIFECYCLE=$life
extra_command() { :; }
# shellcheck disable=SC1090
. "$init"

mkdir -p "$UCI_DIR/values"
printf '%s\n' '1.1.1.1' > "$UCI_DIR/values/dhcp.lan.server"
printf '%s\n' '1' > "$UCI_DIR/values/dhcp.lan.noresolv"
mkdir -p "$tmp/etc/dnsmasq.d"
printf '%s\n' 'server=1.1.1.1' > "$tmp/etc/dnsmasq.d/ikev2.conf"
: > "$DNSMASQ_LOG"
mango_ikev2_dns_off
test ! -f "$tmp/etc/dnsmasq.d/ikev2.conf"
test "$(cat "$UCI_DIR/values/dhcp.lan.server")" = '1.1.1.1'
test "$(cat "$UCI_DIR/values/dhcp.lan.noresolv")" = '1'
grep -q 'dnsmasq restart' "$DNSMASQ_LOG"

# No snippet and no backup: do not restart dnsmasq or edit UCI.
: > "$DNSMASQ_LOG"
mango_ikev2_dns_off
test ! -s "$DNSMASQ_LOG"
test "$(cat "$UCI_DIR/values/dhcp.lan.server")" = '1.1.1.1'

# With a backup, restore the recorded servers and flags.
cat > "$tmp/etc/dns-orig" << 'EOF'
section=lan
noresolv=
filter_aaaa=0
server 8.8.8.8
server 9.9.9.9
confdir /tmp/dnsmasq.d
confdir /etc/mango-ikev2/dnsmasq.d
EOF
# The test etc dir is not the default IKEv2 path, so the snippet dir in the
# backup is skipped only when it matches IKE_ETC. Rewrite that line.
confdir_line="confdir $tmp/etc/dnsmasq.d"
printf '%s\n' 'section=lan' 'noresolv=' 'filter_aaaa=0' 'server 8.8.8.8' 'server 9.9.9.9' 'confdir /tmp/other.d' "$confdir_line" > "$tmp/etc/dns-orig"
rm -f "$UCI_DIR/values/dhcp.lan.server" "$UCI_DIR/values/dhcp.lan.noresolv" "$UCI_DIR/values/dhcp.lan.confdir" "$UCI_DIR/values/dhcp.lan.filter_aaaa"
: > "$DNSMASQ_LOG"
mango_ikev2_dns_off
test ! -f "$tmp/etc/dns-orig"
grep -q '8.8.8.8' "$UCI_DIR/values/dhcp.lan.server"
grep -q '9.9.9.9' "$UCI_DIR/values/dhcp.lan.server"
grep -q '/tmp/other.d' "$UCI_DIR/values/dhcp.lan.confdir"
if grep -q "$tmp/etc/dnsmasq.d" "$UCI_DIR/values/dhcp.lan.confdir"; then
	printf '%s\n' 'IKEv2 confdir was restored' >&2
	exit 1
fi
test "$(cat "$UCI_DIR/values/dhcp.lan.filter_aaaa")" = 0
if [ -f "$UCI_DIR/values/dhcp.lan.noresolv" ]; then
	printf '%s\n' 'empty noresolv was restored' >&2
	exit 1
fi

cat > "$tmp/network.sh" << 'EOF'
#!/bin/sh
# Match OpenWrt: flush unsets the cache, then the getter tests it.
# Under nounset that test aborts unless the caller disabled nounset.
network_flush_cache() { unset __NETWORK_CACHE; }
__network_ifstatus() { [ -z "$__NETWORK_CACHE" ] && __NETWORK_CACHE="cached"; }
network_get_device() {
	__network_ifstatus
	[ -n "${MOCK_WAN_DEV:-}" ] || return 1
	eval "$1=\$MOCK_WAN_DEV"
}
network_get_ipaddr() {
	__network_ifstatus
	[ -n "${MOCK_WAN_IP:-}" ] || return 1
	eval "$1=\$MOCK_WAN_IP"
}
EOF
cat > "$tmp/bin/ip" << 'EOF'
#!/bin/sh
if [ "${1-}" = -4 ] && [ "${XFRM_ADDRS+x}" = x ]; then
	printf '%s\n' "$XFRM_ADDRS"
fi
exit 0
EOF
chmod 755 "$tmp/bin/ip"
export MANGO_IKEV2_NETWORK_SH=$tmp/network.sh PATH="$tmp/bin:$PATH"

MOCK_WAN_DEV=eth0 MOCK_WAN_IP=192.168.0.101 XFRM_ADDRS='inet 10.6.2.12/32' \
	sh "$wan" > "$tmp/wan.out"
test "$(cat "$tmp/wan.out")" = 192.168.0.101

set +e
MOCK_WAN_DEV=eth0 MOCK_WAN_IP=10.6.2.12 XFRM_ADDRS='inet 10.6.2.12/32' \
	sh "$wan" > "$tmp/wan.out" 2>"$tmp/wan.err"
rc=$?
set -e
test "$rc" = 1
grep -q 'tunnel VIP' "$tmp/wan.err"
test ! -s "$tmp/wan.out"

set +e
MOCK_WAN_DEV= MOCK_WAN_IP= XFRM_ADDRS= \
	sh "$wan" > "$tmp/wan.out" 2>"$tmp/wan.err"
rc=$?
set -e
test "$rc" = 1
grep -q 'unavailable' "$tmp/wan.err"

grep -q 'mango-ikev2-wan-addr' "$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-generate"
grep -q 'os.exit(1)' "$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-generate"
grep -q 'set +u' "$wan"

# Generate failure must still start the watchdog, and must not install a config.
cat > "$tmp/bin/generate" << 'EOF'
#!/bin/sh
echo 'generate failed' >&2
exit 1
EOF
cat > "$tmp/bin/peer" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/bin/watch" << 'EOF'
#!/bin/sh
printf '%s\n' started >> "${WATCH_LOG:?}"
sleep 60
EOF
chmod 755 "$tmp/bin/generate" "$tmp/bin/peer" "$tmp/bin/watch"
mkdir -p "$tmp/state" "$tmp/swanctl" "$tmp/etc"
printf '%s\n' 'cidrs' > "$tmp/etc/cn-cidrs.txt"
printf '%s\n' 1 > "$UCI_DIR/values/mango_ikev2.main.enabled"
printf '%s\n' split > "$UCI_DIR/values/mango_ikev2.main.mode"
cat > "$tmp/bin/fw" << 'EOF'
#!/bin/sh
printf '%s\n' fw >> "${FW_LOG:?}"
exit 0
EOF
chmod 755 "$tmp/bin/fw"
: > "$tmp/fw.log"
CONF_DIR=$tmp/state
WATCH_LOG=$tmp/watch.log
export WATCH_LOG \
	FW_LOG=$tmp/fw.log \
	MANGO_IKEV2_FW=$tmp/bin/fw \
	MANGO_IKEV2_GENERATE=$tmp/bin/generate \
	MANGO_IKEV2_PEER_ENGINE=$tmp/bin/peer \
	MANGO_IKEV2_WATCH=$tmp/bin/watch \
	MANGO_IKEV2_WATCH_PID=$tmp/watch.pid \
	MANGO_IKEV2_LOCK=$tmp/apply.lock \
	MANGO_IKEV2_SWANCTL_DIR=$tmp/swanctl \
	MANGO_IKEV2_LOCK_WAIT=5
unset MANGO_IKEV2_LOCK_HELD || true
set +e
mango_ikev2_apply >"$tmp/apply.out" 2>"$tmp/apply.err"
rc=$?
set -e
test "$rc" = 1
grep -q 'swanctl generate failed; watchdog will retry' "$tmp/apply.err"
test "$(cat "$WATCH_LOG")" = started
test -s "$tmp/watch.pid"
test ! -f "$tmp/state/swanctl.conf"
test ! -s "$tmp/fw.log"
if grep -q connected "$tmp/apply.err" "$tmp/apply.out"; then
	printf '%s\n' 'failed generate claimed connected' >&2
	exit 1
fi
kill "$(cat "$tmp/watch.pid")" 2>/dev/null || true
wait "$(cat "$tmp/watch.pid")" 2>/dev/null || true

echo "lifecycle lock nests; DNS off keeps foreign settings; WAN address is not the VIP"
