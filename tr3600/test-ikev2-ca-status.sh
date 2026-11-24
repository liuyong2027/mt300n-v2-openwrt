#!/bin/sh
# Host test: CA file rename, status subject, and loaded flag.
set -eu
ORIG_PATH=$PATH

ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
PKG=$ROOT/luci-app-mango-ikev2
LIB=$PKG/root/usr/lib/mango-ikev2
STATUS=$PKG/root/usr/libexec/mango-ikev2-ca-status
INSTALL=$PKG/root/usr/libexec/mango-ikev2-ca-install
UCI=$PKG/root/etc/uci-defaults/95-mango-ikev2
JS=$PKG/htdocs/luci-static/resources/view/mango-ikev2.js
ACL=$PKG/root/usr/share/rpcd/acl.d/luci-app-mango-ikev2.json
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT INT TERM

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# In the repo this test lives at tr3600/test-ikev2-ca-status.sh; during
# local checkout the files may also be exercised from this directory via
# MANGO_IKEV2_TEST_ROOT.
if [ ! -x "$STATUS" ]; then
	# Allow running against the workspace copies before they are laid out.
	if [ -n "${MANGO_IKEV2_TEST_ROOT:-}" ]; then
		PKG=$MANGO_IKEV2_TEST_ROOT
		LIB=$PKG/lib
		STATUS=$PKG/mango-ikev2-ca-status
		INSTALL=$PKG/mango-ikev2-ca-install
		UCI=$PKG/95-mango-ikev2
		JS=$PKG/mango-ikev2.js
		ACL=$PKG/luci-app-mango-ikev2.json
	fi
fi

[ -f "$STATUS" ] || fail "missing ca-status at $STATUS"
[ -f "$INSTALL" ] || fail "missing ca-install at $INSTALL"
[ -f "$LIB/ca-paths.sh" ] || fail "missing ca-paths.sh"
[ -f "$LIB/ca-print.lua" ] || fail "missing ca-print.lua"

sh -n "$LIB/ca-paths.sh" || fail "sh -n ca-paths.sh"
sh -n "$STATUS" || fail "sh -n ca-status"
sh -n "$INSTALL" || fail "sh -n ca-install"
sh -n "$UCI" || fail "sh -n uci-defaults"

# The default status/install paths and page text must use the generic name.
grep -q 'nordvpn-root-ca.pem' "$LIB/ca-paths.sh" || fail "migration helper missing old name"
grep -q 'CA_NAME=ikev2-root-ca.pem' "$LIB/ca-paths.sh" || fail "generic CA_NAME"
grep -q 'NordVPN Root CA' "$STATUS" && fail "ca-status still hard-codes NordVPN Root CA"
grep -q "/etc/swanctl/x509ca/ikev2-root-ca.pem" "$JS" || fail "JS default install path"
grep -q "/etc/ipsec.d/cacerts/ikev2-root-ca.pem" "$JS" || fail "JS default legacy path"
grep -q "/etc/swanctl/x509ca/nordvpn-root-ca.pem" "$JS" && fail "JS still defaults to nordvpn-root-ca.pem"
grep -q "/etc/swanctl/x509ca/ikev2-root-ca.pem" "$ACL" || fail "ACL new path"
grep -q "/etc/swanctl/x509ca/nordvpn-root-ca.pem" "$ACL" && fail "ACL still only has old path"
pass "filenames and syntax"

# Build a self-signed CA with a non-NordVPN subject, like the VPS root CA.
CERT=$WORKDIR/vps-root.pem
SUBJ='/CN=IKEv2 192.238.238.174 Root CA'
if ! command -v openssl >/dev/null 2>&1; then
	fail "openssl required on the host to mint a test certificate"
fi
openssl req -x509 -newkey rsa:2048 -keyout "$WORKDIR/key.pem" -out "$CERT" \
	-days 3650 -nodes -subj "$SUBJ" >/dev/null 2>&1 \
	|| fail "openssl req failed"

# Lua parser should recover the CN and a not-after date (no openssl on the router).
if command -v lua >/dev/null 2>&1 || command -v lua5.1 >/dev/null 2>&1; then
	LUA=$(command -v lua5.1 2>/dev/null || command -v lua)
	lua_out=$($LUA "$LIB/ca-print.lua" "$CERT")
	printf '%s\n' "$lua_out" | grep -q 'CN=IKEv2 192.238.238.174 Root CA' \
		|| fail "lua parser missed subject: $lua_out"
	printf '%s\n' "$lua_out" | grep -q 'not after' \
		|| fail "lua parser missed not after: $lua_out"
	pass "lua parser reads VPS-style subject"
else
	echo "SKIP: no lua interpreter for ca-print.lua"
fi

SWAN_DIR=$WORKDIR/swanctl
IPSEC_DIR=$WORKDIR/ipsec
mkdir -p "$SWAN_DIR" "$IPSEC_DIR"
cp "$CERT" "$SWAN_DIR/nordvpn-root-ca.pem"
cp "$CERT" "$IPSEC_DIR/nordvpn-root-ca.pem"

# Stub swanctl: first just list the CA as loaded (simulating GL1 after upload).
SWANCTL_BIN=$WORKDIR/bin
mkdir -p "$SWANCTL_BIN"
cat > "$SWANCTL_BIN/swanctl" << 'STUB'
#!/bin/sh
if [ "${1:-}" = "--list-certs" ]; then
	if [ -n "${SWANCTL_LIST:-}" ] && [ -f "$SWANCTL_LIST" ]; then
		cat "$SWANCTL_LIST"
		exit 0
	fi
	exit 0
fi
# load-creds / load-all succeed silently
exit 0
STUB
chmod +x "$SWANCTL_BIN/swanctl"

cat > "$WORKDIR/list-loaded.txt" << 'LST'
List of X.509 End Entity Certificates

List of X.509 CA Certificates

  subject:  "CN=IKEv2 192.238.238.174 Root CA"
  issuer:   "CN=IKEv2 192.238.238.174 Root CA"
  validity:  not before Nov 20 08:00:00 2025, ok
             not after  Nov 18 08:00:00 2036, ok
  serial:    01
  flags:     CA CRLSign 
LST

export PATH="$SWANCTL_BIN:$PATH"
export CA_SWAN_DIR=$SWAN_DIR
export CA_IPSEC_DIR=$IPSEC_DIR
export MANGO_IKEV2_LIBDIR=$LIB
export SWANCTL_LIST=$WORKDIR/list-loaded.txt
# Hide host openssl from status so it exercises pki/lua like the router.
# Keep a copy on PATH under another name? The file_subject_text prefers pki
# then openssl then lua. For the router-like case, hide openssl and pki.
mkdir -p "$WORKDIR/hide"
# Do not put real openssl in PATH for status; swanctl stub is enough.
# lua must stay visible.
NEWPATH=$SWANCTL_BIN
# keep lua, sh, awk, date, wc, grep, mv, cp, mkdir, cat, chmod, rm, tr
for cmd in lua lua5.1 sh awk date wc grep mv cp mkdir cat chmod rm tr printf mktemp basename dirname head tail sed cut env; do
	p=$(command -v "$cmd" 2>/dev/null || true)
	if [ -n "$p" ]; then
		ln -sf "$p" "$WORKDIR/hide/$cmd"
	fi
done
export PATH="$SWANCTL_BIN:$WORKDIR/hide"

out=$("$STATUS")
printf '%s\n' "$out"

printf '%s\n' "$out" | grep -q '^present=1$' || fail "present after migrate: $out"
printf '%s\n' "$out" | grep -q '^legacy_present=1$' || fail "legacy present: $out"
printf '%s\n' "$out" | grep -q '^loaded=1$' || fail "should be loaded for VPS CA: $out"
printf '%s\n' "$out" | grep -q 'subject=CN=IKEv2 192.238.238.174 Root CA$' || fail "subject: $out"
printf '%s\n' "$out" | grep -q 'not_after=Nov 18 08:00:00 2036$' || fail "not_after from swanctl: $out"
printf '%s\n' "$out" | grep -q "path=$SWAN_DIR/ikev2-root-ca.pem" || fail "path after migrate: $out"
[ -s "$SWAN_DIR/ikev2-root-ca.pem" ] || fail "new swan name missing"
[ -e "$SWAN_DIR/nordvpn-root-ca.pem" ] && fail "old swan name still present"
[ -s "$IPSEC_DIR/ikev2-root-ca.pem" ] || fail "new ipsec name missing"
[ -e "$IPSEC_DIR/nordvpn-root-ca.pem" ] && fail "old ipsec name still present"
pass "migration + loaded=1 for VPS root CA"

# Second status call must stay stable and not need the old filename.
out2=$("$STATUS")
printf '%s\n' "$out2" | grep -q '^loaded=1$' || fail "second status loaded: $out2"
pass "status stays loaded after migration"

# File present but a different CA is loaded -> loaded=0, still show file subject.
cat > "$WORKDIR/list-other.txt" << 'LST'
List of X.509 CA Certificates

  subject:  "CN=Some Other Root CA"
  validity:  not before Jan 01 00:00:00 2020, ok
             not after  Jan 01 00:00:00 2030, ok
LST
SWANCTL_LIST=$WORKDIR/list-other.txt
export SWANCTL_LIST
out3=$("$STATUS")
printf '%s\n' "$out3" | grep -q '^loaded=0$' || fail "mismatched CA should be unloaded: $out3"
printf '%s\n' "$out3" | grep -q 'CN=IKEv2 192.238.238.174 Root CA' || fail "should still print file subject: $out3"
pass "loaded=0 when swanctl has a different CA"

# Install must write the generic name and delete leftovers.
SWANCTL_LIST=$WORKDIR/list-loaded.txt
export SWANCTL_LIST
cp "$CERT" "$SWAN_DIR/nordvpn-root-ca.pem"
export MANGO_IKEV2_CA_STATUS=$STATUS
inst=$("$INSTALL" "$CERT")
printf '%s\n' "$inst"
[ -s "$SWAN_DIR/ikev2-root-ca.pem" ] || fail "install did not write new name"
[ -e "$SWAN_DIR/nordvpn-root-ca.pem" ] && fail "install left old name"
printf '%s\n' "$inst" | grep -q '已安装到' || fail "install message: $inst"
printf '%s\n' "$inst" | grep -q '^loaded=1$' || fail "install status not loaded: $inst"
pass "install writes generic name and removes leftover"

# JS syntax
PATH=$ORIG_PATH
if command -v node >/dev/null 2>&1; then
	node --check "$JS" || fail "node --check mango-ikev2.js"
	pass "mango-ikev2.js syntax"
fi

echo 'ALL TESTS PASSED'
