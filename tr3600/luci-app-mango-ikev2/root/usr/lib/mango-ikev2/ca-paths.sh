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
			return 0
		fi
		return 1
	fi
	if [ -s "$_old" ]; then
		mv "$_old" "$_new"
		return 0
	fi
	if [ -e "$_old" ] || [ -L "$_old" ]; then
		rm -f "$_old"
		return 0
	fi
	return 1
}

# Migrate both install and compatibility directories.
# Reloads credentials only when a file was renamed or removed.
mango_ikev2_ca_migrate() {
	_changed=0
	mango_ikev2_ca_migrate_dir "$CA_SWAN_DIR" && _changed=1
	mango_ikev2_ca_migrate_dir "$CA_IPSEC_DIR" && _changed=1
	if [ "$_changed" = 1 ] && command -v swanctl >/dev/null 2>&1; then
		swanctl --load-creds >/dev/null 2>&1 || swanctl --load-all >/dev/null 2>&1 || true
	fi
	return 0
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
# Prefers pki --print so the string matches swanctl; then openssl; then lua.
mango_ikev2_file_subject_text() {
	_file=$1
	[ -s "$_file" ] || return 0
	_out=
	if command -v pki >/dev/null 2>&1; then
		_out=$(pki --print --in "$_file" 2>/dev/null || true)
	elif command -v openssl >/dev/null 2>&1; then
		_out=$(openssl x509 -in "$_file" -noout -subject -nameopt RFC2253,sep_comma_plus_space 2>/dev/null || \
			openssl x509 -in "$_file" -inform DER -noout -subject -nameopt RFC2253,sep_comma_plus_space 2>/dev/null || true)
	fi
	if [ -n "$_out" ]; then
		printf '%s\n' "$_out"
		return 0
	fi
	_lua=
	if command -v lua >/dev/null 2>&1; then
		_lua=lua
	elif command -v lua5.1 >/dev/null 2>&1; then
		_lua=lua5.1
	fi
	if [ -n "$_lua" ] && [ -f "$MANGO_IKEV2_LIBDIR/ca-print.lua" ]; then
		"$_lua" "$MANGO_IKEV2_LIBDIR/ca-print.lua" "$_file" 2>/dev/null || true
	fi
}

# Extract CN=... from a subject string (last CN, unquoted).
mango_ikev2_subject_cn() {
	printf '%s\n' "${1:-}" | awk '
		{
			s = $0
			cn = ""
			while (match(s, /CN=([^,]+)/)) {
				cn = substr(s, RSTART + 3, RLENGTH - 3)
				gsub(/^[[:space:]]+|[[:space:]]+$/, "", cn)
				gsub(/^"|"$/, "", cn)
				s = substr(s, RSTART + RLENGTH)
			}
			if (cn != "") print cn
		}
	'
}
