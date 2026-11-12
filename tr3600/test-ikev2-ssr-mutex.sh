#!/bin/sh
# IKEv2 and SSR Plus+ cannot both own WAN egress.
# Starting SSR with a real node turns IKEv2 off. The other directions stay as they were.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
engine=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-peer-engine
fallback=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-fallback-ssr
patch=$root/tr3600/ssrplus/patch-ssr.py
tmp=$(mktemp -d)
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT
mkdir -p "$tmp/bin" "$tmp/init" "$tmp/uci/values" "$tmp/uci/nodes" "$tmp/state" "$tmp/patch/feeds/helloworld/xray-core" "$tmp/patch/feeds/helloworld/luci-app-ssr-plus/root/etc/init.d" "$tmp/patch/feeds/helloworld/luci-app-ssr-plus/root/usr/bin"

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
			for n in "$state/nodes"/*; do
				[ -e "$n" ] || continue
				printf 'shadowsocksr.%s=servers\n' "$(basename "$n")"
			done
		fi
		;;
	get)
		key=$1
		if [ -f "$state/values/$key" ]; then
			cat "$state/values/$key"
			exit 0
		fi
		case "$key" in
			shadowsocksr.*)
				name=${key#shadowsocksr.}
				case "$name" in
					*.*) ;;
					*)
						if [ -e "$state/nodes/$name" ]; then
							printf '%s\n' servers
							exit 0
						fi
						;;
				esac
				;;
		esac
		exit 1
		;;
	set)
		key=${1%%=*}
		val=${1#*=}
		mkdir -p "$state/values"
		printf '%s\n' "$val" > "$state/values/$key"
		;;
	commit)
		printf 'commit %s\n' "$1" >> "$state/log"
		;;
	*)
		exit 1
		;;
esac
EOF
cat > "$tmp/init/mango_ikev2" << 'EOF'
#!/bin/sh
printf 'ike %s\n' "$1" >> "${CALL_LOG:?}"
if [ "$1" = stop ]; then
	sh "$PEER_ENGINE" yield || true
fi
EOF
cat > "$tmp/init/shadowsocksr" << 'EOF'
#!/bin/sh
printf 'ssr %s\n' "$1" >> "${CALL_LOG:?}"
if [ "$1" = stop ] || [ "$1" = start ] || [ "$1" = restart ]; then
	sh "$PEER_ENGINE" yield || true
fi
EOF
cp "$engine" "$tmp/bin/peer-engine"
cp "$fallback" "$tmp/bin/fallback"
cat > "$tmp/bin/ike-log" << 'EOF'
#!/bin/sh
exit 0
EOF
chmod 755 "$tmp/bin/uci" "$tmp/bin/peer-engine" "$tmp/bin/fallback" "$tmp/bin/ike-log" "$tmp/init/mango_ikev2" "$tmp/init/shadowsocksr"
engine=$tmp/bin/peer-engine
fallback=$tmp/bin/fallback

UCI_DIR=$tmp/uci
CALL_LOG=$tmp/calls
PREV=$tmp/ssr-prev
export UCI_DIR CALL_LOG PEER_ENGINE=$engine
export MANGO_IKEV2_LOG=$tmp/bin/ike-log
export MANGO_IKEV2_SSR_PREV=$PREV
export MANGO_IKEV2_INIT=$tmp/init/mango_ikev2
export SSR_INIT=$tmp/init/shadowsocksr
export MANGO_IKEV2_PEER_ENGINE=$engine
export MANGO_IKEV2_STATE=$tmp/state
export MANGO_IKEV2_FALLBACK_LOCK=$tmp/fallback.lock
PATH="$tmp/bin:$PATH"

put() { printf '%s\n' "$2" > "$UCI_DIR/values/$1"; }
get() { cat "$UCI_DIR/values/$1"; }
reset_calls() { : > "$CALL_LOG"; }
count() { grep -c -- "$1" "$CALL_LOG" || true; }

touch "$UCI_DIR/nodes/node1"
put mango_ikev2.main.enabled 1
put mango_ikev2.main.ssr_fallback 1
put shadowsocksr.global.global_server node1
reset_calls

# 1. Starting SSR while IKEv2 is up disables IKEv2 once and does not loop.
PATH="$tmp/bin:$PATH" sh "$engine" yield
test "$(get mango_ikev2.main.enabled)" = 0
test "$(count '^ike stop$')" = 1
test "$(count '^ssr ')" = 0
test "$(get shadowsocksr.global.global_server)" = node1
reset_calls
PATH="$tmp/bin:$PATH" sh "$engine" yield
test ! -s "$CALL_LOG"
test "$(get mango_ikev2.main.enabled)" = 0

# A nil node is not an egress change, even while IKEv2 is enabled.
put mango_ikev2.main.enabled 1
put shadowsocksr.global.global_server nil
reset_calls
PATH="$tmp/bin:$PATH" sh "$engine" yield
test "$(get mango_ikev2.main.enabled)" = 1
test ! -s "$CALL_LOG"

# 2. Starting SSR when IKEv2 is already off leaves both sides alone.
put mango_ikev2.main.enabled 0
put shadowsocksr.global.global_server node1
reset_calls
PATH="$tmp/bin:$PATH" sh "$engine" yield
test "$(get mango_ikev2.main.enabled)" = 0
test "$(get shadowsocksr.global.global_server)" = node1
test ! -s "$CALL_LOG"

# 3. Enabling IKEv2 still stops SSR and remembers the node.
put mango_ikev2.main.enabled 1
put shadowsocksr.global.global_server node1
reset_calls
PATH="$tmp/bin:$PATH" sh "$engine" claim
test "$(cat "$PREV")" = node1
test "$(get shadowsocksr.global.global_server)" = nil
test "$(count '^ssr stop$')" = 1
test "$(count '^ike ')" = 0

# 5. A manual IKEv2 disable still does not start SSR.
put shadowsocksr.global.global_server node1
reset_calls
PATH="$tmp/bin:$PATH" sh "$engine" release
test "$(get shadowsocksr.global.global_server)" = node1
test ! -s "$CALL_LOG"
test "$(get mango_ikev2.main.enabled)" = 1

# 4. Fallback turns IKEv2 off first, then restore starts SSR exactly once.
put mango_ikev2.main.enabled 1
put shadowsocksr.global.global_server nil
printf '%s\n' node1 > "$PREV"
printf '%s\n' 4 > "$tmp/state/fallback-fail"
reset_calls
PATH="$tmp/bin:$PATH" sh "$fallback"
test "$(get mango_ikev2.main.enabled)" = 0
test "$(get shadowsocksr.global.global_server)" = node1
test "$(count '^ike stop$')" = 1
test "$(count '^ssr restart$')" = 1
test "$(count '^ssr stop$')" = 0
test "$(cat "$tmp/state/fallback-fail")" = 0

# The SSR service hook yields before the upstream start.
printf '%s\n' '	python3 $(PKG_BUILD_DIR)/tools/eip93/overlay.py --go $(STAGING_DIR_HOSTPKG)/bin/go --out $(PKG_BUILD_DIR)/.eip93-overlay' > "$tmp/patch/feeds/helloworld/xray-core/Makefile"
printf '%s\n' 'start() {' ':' '}' 'stop() {' ':' '}' > "$tmp/patch/feeds/helloworld/luci-app-ssr-plus/root/etc/init.d/shadowsocksr"
printf '%s\n' 'gen_include_nft() {' '	cat <<-EOF >>"$FWI"' '		true' '	EOF' '	chmod +x "$FWI"' '}' > "$tmp/patch/feeds/helloworld/luci-app-ssr-plus/root/usr/bin/ssr-rules"
python3 "$patch" "$tmp/patch" >/dev/null
python3 - "$tmp/patch/feeds/helloworld/luci-app-ssr-plus/root/etc/init.d/shadowsocksr" << 'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
body = text[text.index("\nstart() {"):]
assert body.index("mango-ikev2-peer-engine yield") < body.index("start_without_cudy_gate")
PY

echo "SSR start yields IKEv2; claim, release, and fallback stay exclusive"
