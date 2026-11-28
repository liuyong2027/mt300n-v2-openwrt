#!/bin/sh
set -eu
pkg=$1
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir "$work/bin" "$work/swanctl" "$work/ipsec"
if [ -n "${2:-}" ]; then
    cp "$2/first.pem" "$2/second.pem" "$2/second.der" "$work/"
else
    for name in first second; do
        openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj '/CN=TR3600 Test Root CA' \
            -keyout "$work/key.pem" -out "$work/$name.pem" 2>/dev/null
    done
    openssl x509 -in "$work/second.pem" -outform DER -out "$work/second.der"
fi
cat > "$work/bin/swanctl" <<'EOF'
#!/bin/sh
case "$*" in
    '--list-certs --type x509 --flag ca --pem') cat "$SWANCTL_CERT" ;;
    '--load-creds --noprompt') echo reload >> "$SWANCTL_TEST_LOG" ;;
    *) exit 1 ;;
esac
EOF
cp "$pkg/root/usr/libexec/mango-ikev2-ca-status" "$work/ca-status"
chmod +x "$work/bin/swanctl" "$work/ca-status"
export PATH="$work/bin:$PATH"
export CA_SWAN_DIR="$work/swanctl" CA_IPSEC_DIR="$work/ipsec"
export MANGO_IKEV2_LIBDIR="$pkg/root/usr/lib/mango-ikev2"
export MANGO_IKEV2_CA_STATUS="$work/ca-status"
export MANGO_IKEV2_LUA="$(command -v lua5.1 || command -v lua)"
export SWANCTL_CERT="$work/first.pem" SWANCTL_TEST_LOG="$work/reload"
installer=$pkg/root/usr/libexec/mango-ikev2-ca-install

cp "$work/first.pem" "$CA_SWAN_DIR/nordvpn-root-ca.pem"
cp "$work/first.pem" "$CA_IPSEC_DIR/nordvpn-root-ca.pem"
sh "$MANGO_IKEV2_CA_STATUS" > "$work/status"
grep -Fx 'loaded=1' "$work/status"
grep -Fx 'subject=CN=TR3600 Test Root CA' "$work/status"
grep -Eq '^not_after=[A-Z][a-z]+ ' "$work/status"
test ! -e "$CA_SWAN_DIR/nordvpn-root-ca.pem"
test ! -e "$CA_IPSEC_DIR/nordvpn-root-ca.pem"
cmp "$work/first.pem" "$CA_SWAN_DIR/ikev2-root-ca.pem"
cmp "$work/first.pem" "$CA_IPSEC_DIR/ikev2-root-ca.pem"

# A second certificate with the same subject must be distinguished by its bytes.
sh "$installer" "$work/second.der" > "$work/status"
grep -Fx 'loaded=0' "$work/status"
cmp "$CA_SWAN_DIR/ikev2-root-ca.pem" "$CA_IPSEC_DIR/ikev2-root-ca.pem"
SWANCTL_CERT="$work/second.pem"
sh "$MANGO_IKEV2_CA_STATUS" | grep -Fx 'loaded=1'
cp "$CA_SWAN_DIR/ikev2-root-ca.pem" "$work/installed"
printf 'malformed upload\n' > "$work/bad"
if sh "$installer" "$work/bad"; then
    echo 'Invalid upload was accepted' >&2
    exit 1
fi
cmp "$work/installed" "$CA_SWAN_DIR/ikev2-root-ca.pem"
cmp "$work/installed" "$CA_IPSEC_DIR/ikev2-root-ca.pem"

SWANCTL_CERT="$work/first.pem"
sh "$installer" "$work/first.pem" | grep -Fx 'loaded=1'
cmp "$work/first.pem" "$CA_SWAN_DIR/ikev2-root-ca.pem"
cmp "$work/first.pem" "$CA_IPSEC_DIR/ikev2-root-ca.pem"
test "$(wc -l < "$work/reload")" -eq 3
echo 'PASS IKEv2 root CA migration, PEM/DER replacement, and exact loaded status'
