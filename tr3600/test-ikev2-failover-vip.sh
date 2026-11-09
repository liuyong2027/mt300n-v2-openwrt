#!/bin/sh
# Healthy IKEv2 recheck must not flush xfrm-mango. Dial and dead-tunnel paths still do.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
script=$root/tr3600/luci-app-mango-ikev2/root/usr/libexec/mango-ikev2-failover
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/state"
printf '%s\n' mango > "$tmp/state/active"
printf '%s\n' mango > "$tmp/state/logged-up"

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
printf 'unexpected swanctl %s\n' "$*" >&2
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
exit 0
EOF
chmod 755 "$tmp/bin/uci" "$tmp/bin/swanctl" "$tmp/bin/ip" "$tmp/bin/ping"

IP_LOG=$tmp/ip.log
export IP_LOG
: > "$IP_LOG"
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
test "$(cat "$tmp/state/active")" = mango
test "$(cat "$tmp/state/fail-count")" = 0

python3 - "$script" << 'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
assert text.count("clear_vip") == 4, text.count("clear_vip")
assert "prepare_dial() {\n\tclear_vip\n" in text
assert '\tvip=$(peer_vip "$peer")\n\tclear_vip\n\tpin_vip "$vip"\n' in text
assert 'log_event fail "$active" "datapath dead; redial"\n\tterminate_all\n\tclear_vip\n' in text
start = text.index("\tif datapath_ok; then\n")
end = text.index("\tfi\n\t# SA looks fine but tunnel probe failed", start)
healthy = text[start:end]
assert "clear_vip" not in healthy
assert '\tpin_vip "$vip"\n' in healthy
print("healthy recheck keeps the VIP; dial and dead-tunnel paths still flush")
PY
