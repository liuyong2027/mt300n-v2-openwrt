#!/bin/sh
# Status LED probes: direct stays on the WAN. IKEv2 split/global/gfw uses xfrm-mango.
# SSR split/global/gfw stays unmarked so its OUTPUT redirect still applies.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT
mkdir -p "$tmp/bin"

python3 - "$root/tr3600/led-probe/mango-connectivity-probe" "$root/tr3600/ssrplus/profile.py" "$tmp/probe" << 'PY'
import importlib.util
import sys
from pathlib import Path
source, profile, dest = sys.argv[1:]
spec = importlib.util.spec_from_file_location('ssrplus_profile', profile)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Path(dest).write_text(module.ssrplus_connectivity_probe(Path(source).read_text()), encoding='utf-8')
text = Path(dest).read_text()
assert 'socks5h://127.0.0.1:10809' not in text
assert '--interface xfrm-mango' in text
assert 'xfrm-mango missing' in text
assert '/tmp/cudy-connectivity-error.' in text
assert '/tmp/mango-connectivity-error.' not in text
PY
chmod 755 "$tmp/probe"

cat > "$tmp/bin/curl" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${CURL_LOG:?}"
printf '204 connect=0 tls=0 first=0 total=0'
exit 0
EOF
cat > "$tmp/bin/uci" << 'EOF'
#!/bin/sh
key=$3
case "$key" in
	mango_ikev2.main.enabled) printf '%s\n' "${UCI_IKE_ENABLED:-0}" ;;
	mango_ikev2.main.mode) printf '%s\n' "${UCI_IKE_MODE:-split}" ;;
	*) exit 1 ;;
esac
EOF
cat > "$tmp/bin/ip" << 'EOF'
#!/bin/sh
if [ "${XFRM_PRESENT:-0}" = 1 ]; then
	exit 0
fi
exit 1
EOF
chmod 755 "$tmp/bin/curl" "$tmp/bin/uci" "$tmp/bin/ip"

CURL_LOG=$tmp/curl.log
export CURL_LOG
run() {
	: > "$CURL_LOG"
	PATH="$tmp/bin:$PATH" UCI_IKE_ENABLED="${1:-0}" UCI_IKE_MODE="${2:-split}" XFRM_PRESENT="${3:-0}" \
		sh "$tmp/probe" "$4" > "$tmp/out"
}

# Direct stays on the WAN even if an IKEv2 tunnel exists.
run 1 split 1 direct
grep -q -- '--noproxy' "$CURL_LOG"
grep -q 'https://www.baidu.com/' "$CURL_LOG"
if grep -q -- '--interface' "$CURL_LOG"; then
	printf '%s\n' 'direct probe used the tunnel' >&2
	exit 1
fi

# IKEv2 split/global/gfw leaves on xfrm-mango.
for mode in split global gfw; do
	run 1 "$mode" 1 "$mode"
	grep -q -- '--interface xfrm-mango' "$CURL_LOG"
	grep -q 'https://www.google.com/generate_204' "$CURL_LOG"
	if grep -q -- '--proxy' "$CURL_LOG" || grep -q -- '--noproxy' "$CURL_LOG"; then
		printf '%s\n' "$mode probe used the WAN proxy flags" >&2
		exit 1
	fi
done

# A missing tunnel fails before curl, instead of falling through to the WAN.
: > "$CURL_LOG"
set +e
PATH="$tmp/bin:$PATH" UCI_IKE_ENABLED=1 UCI_IKE_MODE=split XFRM_PRESENT=0 \
	sh "$tmp/probe" split > "$tmp/out"
rc=$?
set -e
test "$rc" = 1
grep -q 'xfrm-mango missing' "$tmp/out"
test ! -s "$CURL_LOG"

# SSR egress stays unmarked so its OUTPUT redirect still applies.
run 0 split 0 split
if grep -q -- '--interface' "$CURL_LOG" || grep -q -- '--proxy' "$CURL_LOG"; then
	printf '%s\n' 'SSR probe was pinned to the IKEv2 tunnel' >&2
	exit 1
fi
grep -q 'https://www.google.com/generate_204' "$CURL_LOG"

# IKEv2 direct mode is not the tunnel engine; an unmarked split probe is SSR's path.
run 1 direct 1 split
if grep -q -- '--interface' "$CURL_LOG"; then
	printf '%s\n' 'IKEv2 direct mode forced the tunnel interface' >&2
	exit 1
fi

echo "status probes use xfrm-mango for IKEv2 and stay unmarked for SSR"
