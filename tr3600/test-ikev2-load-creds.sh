#!/bin/sh
# EAP secrets live in the generated swanctl file. load-conns does not load
# them, and load-creds without --file misses that file. Both refresh paths
# must load creds from the file before connections or initiate.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
script=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-failover
init=$root/tr3600/luci-app-mango-ikev2/root/etc/init.d/mango_ikev2
sh -n "$script"
sh -n "$init"
tmp=$(mktemp -d)
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT
mkdir -p "$tmp/bin" "$tmp/state" "$tmp/swanctl" "$tmp/etc"

cat > "$tmp/bin/uci" << 'EOF'
#!/bin/sh
key=${3-}
case "$key" in
	mango_ikev2.main.enabled) printf '%s\n' 1 ;;
	mango_ikev2.main.mode) printf '%s\n' split ;;
	mango_ikev2.main.server2|mango_ikev2.main.server3) exit 1 ;;
	mango_ikev2.main.ssr_fallback) printf '%s\n' 0 ;;
	mango_ikev2.main.ssr_fallback_fails) printf '%s\n' 6 ;;
	*) exit 1 ;;
esac
EOF
cat > "$tmp/bin/swanctl" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${SWANCTL_LOG:?}"
exit 0
EOF
cat > "$tmp/bin/ip" << 'EOF'
#!/bin/sh
case "$*" in
	"link show xfrm-mango") exit 0 ;;
	"link set xfrm-mango mtu 1280 up") exit 0 ;;
esac
exit 0
EOF
cat > "$tmp/bin/generate" << 'EOF'
#!/bin/sh
printf '%s\n' 'secrets { eap-mango { secret = "test" } }'
exit 0
EOF
cat > "$tmp/bin/fw" << 'EOF'
#!/bin/sh
exit 0
EOF
cat > "$tmp/bin/event-log" << 'EOF'
#!/bin/sh
exit 0
EOF
chmod 755 "$tmp/bin/uci" "$tmp/bin/swanctl" "$tmp/bin/ip" "$tmp/bin/generate" "$tmp/bin/fw" "$tmp/bin/event-log"
printf '%s\n' mango > "$tmp/state/active"
printf '%s\n' 0 > "$tmp/state/fail-count"
printf '%s\n' 0 > "$tmp/state/fallback-fail"
: > "$tmp/swanctl.log"
: > "$tmp/charon.log"
export SWANCTL_LOG=$tmp/swanctl.log
export MANGO_IKEV2_LOG=$tmp/bin/event-log
export MANGO_IKEV2_LOCK=$tmp/lock MANGO_IKEV2_LOCK_WAIT=2
export MANGO_IKEV2_LIFECYCLE=$root/tr3600/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/lifecycle.sh
export MANGO_IKEV2_GENERATE=$tmp/bin/generate
export MANGO_IKEV2_FW=$tmp/bin/fw
export MANGO_IKEV2_SWANCTL_DIR=$tmp/swanctl
export MANGO_IKEV2_STATE=$tmp/state
export MANGO_IKEV2_POST_TERM_WAIT=0 MANGO_IKEV2_SA_POLL=0
export MANGO_IKEV2_CHARON_LOG=$tmp/charon.log MANGO_IKEV2_SNIP=$tmp/snip
export PATH="$tmp/bin:$PATH"

assert_order() {
	log=$1
	file=$2
	creds=$(grep -n -F -- "--load-creds --noprompt --file $file" "$log" | head -n 1 | cut -d: -f1)
	conns=$(grep -n -F -- '--load-conns' "$log" | head -n 1 | cut -d: -f1)
	init_line=$(grep -n -F -- '--initiate' "$log" | head -n 1 | cut -d: -f1)
	test -n "$creds"
	test -n "$conns"
	test "$creds" -lt "$conns"
	if [ -n "$init_line" ]; then
		test "$conns" -lt "$init_line"
	fi
	if grep -F -- '--load-conns --noprompt' "$log" >/dev/null; then
		echo 'load-conns still uses --noprompt' >&2
		exit 1
	fi
	if grep -E -- '--load-creds( |$)' "$log" | grep -v -- '--file ' >/dev/null; then
		echo 'load-creds missing --file' >&2
		exit 1
	fi
}

# Down SA: failover refreshes the WAN bind and dials.
PATH="$tmp/bin:$PATH" sh "$script" >/dev/null 2>"$tmp/dial.err" || true
test -s "$tmp/state/swanctl.conf"
assert_order "$tmp/swanctl.log" "$tmp/state/swanctl.conf"

# init install path uses the same creds-then-conns order.
: > "$tmp/swanctl.log"
staged=$tmp/staged.conf
printf '%s\n' 'secrets { eap-mango { secret = "installed" } }' > "$staged"
(
	extra_command() { :; }
	# shellcheck disable=SC1090
	. "$init"
	mango_ikev2_install_swanctl "$staged"
)
assert_order "$tmp/swanctl.log" "$tmp/state/swanctl.conf"
grep -q 'installed' "$tmp/state/swanctl.conf"

echo "EAP creds are loaded from the generated swanctl file before connections"
