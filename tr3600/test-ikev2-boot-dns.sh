#!/bin/sh
# Boot apply can fail before dns_on. The later failover dial must install
# the split dnsmasq snippet once, and a healthy tick must not restart dnsmasq.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
init=$root/tr3600/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2
script=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-failover
life=$root/tr3600/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/lifecycle.sh
tmp=$(mktemp -d)
watch_pid=
cleanup() {
	if [ -n "${watch_pid:-}" ] && [ -f "$tmp/watch.pid" ]; then
		kill "$(cat "$tmp/watch.pid")" 2>/dev/null || true
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
			dhcp) printf '%s\n' 'dhcp.lan=dnsmasq' ;;
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
cat > "$tmp/bin/generate" << 'EOF'
#!/bin/sh
if [ "${1-}" = dnsmasq ]; then
	if [ "${DNS_FAIL:-}" = 1 ]; then
		echo 'dnsmasq generate failed' >&2
		exit 1
	fi
	cat << 'SNIP'
no-resolv
filter-AAAA
server=223.5.5.5
server=119.29.29.29
server=/google.com/1.1.1.1
server=/google.com/8.8.8.8
SNIP
	exit 0
fi
if [ "${WAN_FAIL:-}" = 1 ]; then
	echo 'WAN IPv4 unavailable' >&2
	exit 1
fi
printf '%s\n' '# swanctl'
exit 0
EOF
cat > "$tmp/bin/peer" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/bin/fw" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/bin/failover" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/bin/watch" << 'EOF'
#!/bin/sh
printf '%s\n' started >> "${WATCH_LOG:?}"
sleep 60
EOF
cat > "$tmp/init/dnsmasq" << 'EOF'
#!/bin/sh
printf '%s\n' "$1" >> "${DNSMASQ_LOG:?}"
exit 0
EOF
cat > "$tmp/bin/swanctl" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${SWANCTL_LOG:?}"
case "${1-}" in
	--list-sas)
		if [ -f "${SWANCTL_DOWN:-}" ]; then
			exit 0
		fi
		cat "${SAS_FILE:?}"
		exit 0
		;;
	--initiate)
		rm -f "${SWANCTL_DOWN:-}"
		exit 0
		;;
esac
exit 0
EOF
cat > "$tmp/bin/ip" << 'EOF'
#!/bin/sh
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
	*"-4 addr show"*)
		if [ -f "${VIP_PINNED:-}" ]; then
			printf '%s\n' 'inet 10.6.1.169/32 scope global xfrm-mango'
		fi
		;;
	*"addr replace 10.6.1.169/32 dev xfrm-mango")
		touch "${VIP_PINNED:?}"
		;;
	*"-4 rule show"*)
		if [ -f "${RULE_UP:-}" ]; then
			printf '%s\n' '10001: from all fwmark 0x101 lookup 101'
		fi
		;;
	*"rule add priority 10001"*)
		touch "${RULE_UP:?}"
		;;
esac
exit 0
EOF
cat > "$tmp/bin/pidof" << 'EOF'
#!/bin/sh
[ "$1" = charon ]
EOF
cat > "$tmp/bin/ping" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/sas" << 'EOF'
mango: #1, ESTABLISHED, IKEv2
  local 192.0.2.1[10.6.1.169]
  remote vpn.example[203.0.113.5]
  mango: #1, INSTALLED, TUNNEL
    local  10.6.1.169/32
    remote 0.0.0.0/0
EOF
chmod 755 "$tmp/bin/"* "$tmp/init/dnsmasq"
python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1]); s.listen(1)' "$tmp/vici"
printf '%s\n' 1 > "$tmp/uci/values/mango_ikev2.main.enabled"
printf '%s\n' split > "$tmp/uci/values/mango_ikev2.main.mode"
printf '%s\n' cidrs > "$tmp/etc/cn-cidrs.txt"
printf '%s\n' mango > "$tmp/state/active"
: > "$tmp/dnsmasq.log"
: > "$tmp/watch.log"
: > "$tmp/swanctl.log"
touch "$tmp/swan-down"

export UCI_DIR=$tmp/uci \
	DNSMASQ_LOG=$tmp/dnsmasq.log \
	WATCH_LOG=$tmp/watch.log \
	SWANCTL_LOG=$tmp/swanctl.log \
	SWANCTL_DOWN=$tmp/swan-down \
	SAS_FILE=$tmp/sas \
	XFRM_UP=$tmp/xfrm-up \
	VIP_PINNED=$tmp/vip \
	RULE_UP=$tmp/rule \
	WAN_FAIL=1 \
	DNS_FAIL=1 \
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
	MANGO_IKEV2_POST_TERM_WAIT=0 \
	MANGO_IKEV2_SA_POLL=0 \
	PATH="$tmp/bin:$PATH"

# First boot apply: WAN is down, so DNS is not installed and dnsmasq stays put.
set +e
(
	extra_command() { :; }
	# shellcheck disable=SC1090
	. "$init"
	mango_ikev2_apply
) >"$tmp/apply.out" 2>"$tmp/apply.err"
rc=$?
set -e
test "$rc" = 1
grep -q 'swanctl generate failed; watchdog will retry' "$tmp/apply.err"
test -s "$tmp/watch.pid"
watch_pid=$(cat "$tmp/watch.pid")
test ! -s "$tmp/etc/dnsmasq.d/ikev2.conf"
test ! -f "$tmp/uci/values/dhcp.lan.noresolv"
test ! -s "$tmp/dnsmasq.log"
kill "$watch_pid" 2>/dev/null || true
wait "$watch_pid" 2>/dev/null || true
watch_pid=

# A failed dnsmasq generate must not turn on noresolv.
(
	extra_command() { :; }
	# shellcheck disable=SC1090
	. "$init"
	if mango_ikev2_dns_on; then
		echo 'empty generate installed DNS' >&2
		exit 1
	fi
) >"$tmp/dns-fail.out" 2>"$tmp/dns-fail.err"
test ! -s "$tmp/etc/dnsmasq.d/ikev2.conf"
test ! -f "$tmp/uci/values/dhcp.lan.noresolv"

# Later tick: WAN is up, the dial succeeds, and split DNS is installed once.
WAN_FAIL=0
DNS_FAIL=0
export WAN_FAIL DNS_FAIL
PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state sh "$script" >/dev/null 2>"$tmp/retry.err"
conf=$tmp/etc/dnsmasq.d/ikev2.conf
grep -q '^no-resolv$' "$conf"
grep -q '^filter-AAAA$' "$conf"
grep -q '^server=223.5.5.5$' "$conf"
grep -q '^server=/google.com/1.1.1.1$' "$conf"
grep -q '^server=/google.com/8.8.8.8$' "$conf"
test "$(cat "$tmp/uci/values/dhcp.lan.noresolv")" = 1
test "$(cat "$tmp/uci/values/dhcp.lan.filter_aaaa")" = 1
grep -qx "$tmp/etc/dnsmasq.d" "$tmp/uci/values/dhcp.lan.confdir"
test "$(cat "$tmp/dnsmasq.log")" = restart

# The next healthy tick keeps the snippet and does not restart dnsmasq.
rm -f "$tmp/swan-down"
PATH="$tmp/bin:$PATH" MANGO_IKEV2_STATE=$tmp/state sh "$script" >/dev/null 2>"$tmp/healthy.err"
test "$(cat "$tmp/dnsmasq.log")" = restart
grep -q '^no-resolv$' "$conf"

echo "boot retry installs split DNS once; a healthy tick does not restart dnsmasq"
