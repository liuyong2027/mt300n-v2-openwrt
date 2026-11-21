#!/bin/sh
# WAN ifup regenerates the IKEv2 dnsmasq snippet only when ISP resolvers differ.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
hook=$root/tr3600/luci-app-mango-ikev2/root/etc/hotplug.d/iface/97-mango-ikev2-dns
model=$root/tr3600/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/model.lua
sh -n "$hook"
test -x "$hook"
tmp=$(mktemp -d)
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT
mkdir -p "$tmp/bin" "$tmp/etc/dnsmasq.d" "$tmp/lib"

cat > "$tmp/bin/uci" << 'EOF'
#!/bin/sh
if [ "${1-}" = -q ]; then
	shift
fi
key=${2-}
case "$key" in
	mango_ikev2.main.enabled)
		if [ "${IKE_ENABLED:-1}" = 1 ]; then
			printf '%s\n' 1
			exit 0
		fi
		exit 1
		;;
esac
exit 1
EOF
cat > "$tmp/bin/logger" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${LOGGER_LOG:?}"
EOF
cat > "$tmp/lib/dns.sh" << 'EOF'
mango_ikev2_dns_on() {
	printf '%s\n' regenerated >> "${DNS_ON_LOG:?}"
	return 0
}
EOF
chmod 755 "$tmp/bin/uci" "$tmp/bin/logger" "$hook"
printf '%s\n' 'server=202.106.46.151' 'server=202.106.195.68' 'server=/google.com/1.1.1.1' > "$tmp/etc/dnsmasq.d/ikev2.conf"
printf '%s\n' 'nameserver 127.0.0.1' 'nameserver 202.106.46.151' 'nameserver 202.106.195.68' > "$tmp/resolv"
: > "$tmp/logger.log"
: > "$tmp/dns-on.log"
export PATH="$tmp/bin:$PATH"
export MANGO_IKEV2_DNS_LOCK=$tmp/lock
export MANGO_IKEV2_DNS_REFRESH_DELAY=0
export MANGO_IKEV2_ETC=$tmp/etc
export MANGO_IKEV2_RESOLV_AUTO=$tmp/resolv
export MANGO_IKEV2_DNS_SH=$tmp/lib/dns.sh
export MANGO_IKEV2_DNSMASQ_INIT=$tmp/bin/dnsmasq
export LOGGER_LOG=$tmp/logger.log DNS_ON_LOG=$tmp/dns-on.log

# The hook returns immediately and finishes the check in the background.
settle() { sleep 0.4; }

ACTION=ifup INTERFACE=wan IKE_ENABLED=1 sh "$hook"
settle
test ! -s "$tmp/dns-on.log"

printf '%s\n' 'nameserver 1.2.3.4' > "$tmp/resolv"
ACTION=ifupdate INTERFACE=wan sh "$hook"
settle
test "$(cat "$tmp/dns-on.log")" = regenerated
grep -q 'ISP DNS changed: 202.106.46.151 202.106.195.68  -> 1.2.3.4 ' "$tmp/logger.log"

: > "$tmp/dns-on.log"
ACTION=ifup INTERFACE=lan sh "$hook"
settle
test ! -s "$tmp/dns-on.log"

IKE_ENABLED=0 ACTION=ifup INTERFACE=wan sh "$hook"
settle
test "$(wc -l < "$tmp/dns-on.log" | tr -d ' ')" = 0

# model.lua reads the same resolvers and falls back to the ISP pair.
printf '%s\n' 'nameserver 127.0.0.1' 'nameserver 8.8.4.4' > "$tmp/resolv"
got=$(MANGO_IKEV2_RESOLV_AUTO=$tmp/resolv lua5.1 -e "local M=dofile('$model'); print(table.concat(M.domestic_dns, ' '))")
test "$got" = '8.8.4.4'
got=$(MANGO_IKEV2_RESOLV_AUTO=$tmp/missing lua5.1 -e "local M=dofile('$model'); print(table.concat(M.domestic_dns, ' '))")
test "$got" = '202.106.46.151 202.106.195.68'

echo "WAN DNS hotplug is a no-op when unchanged and regenerates a stale snippet"
