# Shared IKEv2 root CA paths and legacy-name migration.
# Sourced by ca-install, ca-status, and uci-defaults.
# shellcheck shell=sh

: "${CA_SWAN_DIR:=/etc/swanctl/x509ca}"
: "${CA_IPSEC_DIR:=/etc/ipsec.d/cacerts}"
: "${MANGO_IKEV2_LIBDIR:=/usr/lib/mango-ikev2}"

CA_NAME=ikev2-root-ca.pem
CA_NAME_OLD=nordvpn-root-ca.pem
CA_SWAN=$CA_SWAN_DIR/$CA_NAME
CA_IPSEC=$CA_IPSEC_DIR/$CA_NAME

# Rename nordvpn-root-ca.pem -> ikev2-root-ca.pem in one directory.
# If the new name already exists, drop the old copy so swanctl does not
# load the same CA twice. Returns 0 when the directory changed.
mango_ikev2_ca_migrate_dir() {
	_dir=$1
	[ -n "$_dir" ] || return 1
	mkdir -p "$_dir"
	_old=$_dir/$CA_NAME_OLD
	_new=$_dir/$CA_NAME
	if [ -s "$_new" ]; then
		if [ -e "$_old" ] || [ -L "$_old" ]; then
			rm -f "$_old"
			return $?
		fi
		return 1
	fi
	if [ -s "$_old" ]; then
		mv "$_old" "$_new"
		return $?
	fi
	if [ -e "$_old" ] || [ -L "$_old" ]; then
		rm -f "$_old"
		return $?
	fi
	return 1
}

# Migrate both install and compatibility directories.
# Reloads credentials only when a file was renamed or removed.
mango_ikev2_ca_migrate() {
	_changed=0
	mango_ikev2_ca_migrate_dir "$CA_SWAN_DIR" && _changed=1
	mango_ikev2_ca_migrate_dir "$CA_IPSEC_DIR" && _changed=1
	[ "$_changed" = 0 ] || mango_ikev2_ca_reload
	return 0
}

# Reload only credentials. The TR3600 service owns its connection lifecycle.
mango_ikev2_ca_reload() {
	if command -v swanctl >/dev/null 2>&1; then
		swanctl --load-creds --noprompt >/dev/null 2>&1 || true
	fi
}

# Read the first "subject:" line from pki/swanctl-style text on stdin.
# Prints the unquoted subject, or nothing.
mango_ikev2_parse_subject_line() {
	awk '
		tolower($0) ~ /subject:/ {
			sub(/^[^:]*:[[:space:]]*/, "")
			gsub(/^"/, "")
			sub(/"[[:space:]]*$/, "")
			gsub(/^[[:space:]]+|[[:space:]]+$/, "")
			if ($0 != "") { print; exit }
		}
	'
}

# Read not-after from pki/swanctl-style text on stdin.
mango_ikev2_parse_not_after_line() {
	awk '
		/not after/ {
			line = $0
			sub(/^.*not after[[:space:]]+/, "", line)
			sub(/,.*/, "", line)
			gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
			if (line != "") { print line; exit }
		}
	'
}

# Print the subject of a PEM/DER file to stdout, or nothing.
# The bundled Lua reader also works on images without the OpenSSL CLI.
mango_ikev2_file_subject_text() {
	_file=$1
	[ -s "$_file" ] || return 0
	if command -v pki >/dev/null 2>&1; then
		_out=$(pki --print --in "$_file" 2>/dev/null || true)
		if [ -n "$_out" ]; then
			printf '%s\n' "$_out"
			return 0
		fi
	fi
	"${MANGO_IKEV2_LUA:-lua}" "$MANGO_IKEV2_LIBDIR/ca-print.lua" "$_file" 2>/dev/null
}

# Emit one continuous base64 body per certificate so status can match
# the exact certificate even when the file and swanctl wrap it differently.
mango_ikev2_pem_bodies() {
	awk '
		/-----BEGIN CERTIFICATE-----/ { active=1; body=""; next }
		/-----END CERTIFICATE-----/ { if (active && body != "") print body; active=0; next }
		active { gsub(/[[:space:]]/, ""); body=body $0 }
	'
}
