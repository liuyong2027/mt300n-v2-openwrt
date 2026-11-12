# IKEv2 dnsmasq snippet. Callers set IKE_ETC and DNSMASQ_INIT.
# A failed or empty generate must not leave noresolv=1 on a blank file.

mango_ikev2_dns_section() {
	uci show dhcp 2>/dev/null | sed -n 's/^dhcp\.\([^=]*\)=dnsmasq$/\1/p' | head -n 1
}

mango_ikev2_dns_on() {
	local sec conf
	sec=$(mango_ikev2_dns_section)
	[ -n "$sec" ] || return 1
	mkdir -p "$IKE_ETC/dnsmasq.d"
	conf=$IKE_ETC/dnsmasq.d/ikev2.conf
	if [ ! -s "$IKE_ETC/dns-orig" ]; then
		{
			echo "section=$sec"
			echo "noresolv=$(uci -q get "dhcp.${sec}.noresolv" || true)"
			echo "filter_aaaa=$(uci -q get "dhcp.${sec}.filter_aaaa" || true)"
			uci -q get "dhcp.${sec}.server" | tr ' ' '\n' | sed 's/^/server /'
			uci -q get "dhcp.${sec}.confdir" | tr ' ' '\n' | sed 's/^/confdir /'
		} > "$IKE_ETC/dns-orig"
	fi
	# Write to a temp file first so a failed/empty generate cannot leave
	# noresolv=1 pointing at a blank snippet (local DNS REFUSED).
	if ! "${MANGO_IKEV2_GENERATE:-/usr/libexec/mango-ikev2-generate}" dnsmasq > "$conf.tmp" || [ ! -s "$conf.tmp" ]; then
		rm -f "$conf.tmp"
		return 1
	fi
	mv "$conf.tmp" "$conf"
	uci set "dhcp.${sec}.noresolv=1"
	uci set "dhcp.${sec}.filter_aaaa=1"
	uci -q delete "dhcp.${sec}.server"
	if ! uci -q get "dhcp.${sec}.confdir" | tr ' ' '\n' | grep -qx "$IKE_ETC/dnsmasq.d"; then
		uci add_list "dhcp.${sec}.confdir=$IKE_ETC/dnsmasq.d"
	fi
	uci commit dhcp
	"$DNSMASQ_INIT" restart
}

mango_ikev2_dns_off() {
	local sec line val has_server=0 had_snip=0 orig
	orig=$IKE_ETC/dns-orig
	# Always drop the IKEv2 conf snippet. Without a backup, do not touch
	# dnsmasq server/confdir/noresolv/filter_aaaa that IKEv2 did not record.
	if [ -f "$IKE_ETC/dnsmasq.d/ikev2.conf" ]; then
		had_snip=1
	fi
	rm -f "$IKE_ETC/dnsmasq.d/ikev2.conf"
	if [ ! -s "$orig" ]; then
		if [ "$had_snip" = 1 ]; then
			"$DNSMASQ_INIT" restart
		fi
		return 0
	fi
	sec=$(sed -n 's/^section=//p' "$orig" | head -n 1)
	[ -n "$sec" ] || sec=$(mango_ikev2_dns_section)
	[ -n "$sec" ] || return 0
	uci -q delete "dhcp.${sec}.server"
	uci -q delete "dhcp.${sec}.confdir"
	uci -q delete "dhcp.${sec}.noresolv"
	uci -q delete "dhcp.${sec}.filter_aaaa"
	while IFS= read -r line; do
		case "$line" in
			section=*|noresolv=*|filter_aaaa=*) ;;
			'server '*)
				uci add_list "dhcp.${sec}.server=${line#server }"
				has_server=1
				;;
			'confdir '*)
				# Never put the IKEv2 snippet dir back while tearing down.
				[ "${line#confdir }" = "$IKE_ETC/dnsmasq.d" ] && continue
				uci add_list "dhcp.${sec}.confdir=${line#confdir }"
				;;
		esac
	done < "$orig"
	val=$(sed -n 's/^noresolv=//p' "$orig" | head -n 1)
	[ -n "$val" ] && uci set "dhcp.${sec}.noresolv=$val"
	val=$(sed -n 's/^filter_aaaa=//p' "$orig" | head -n 1)
	[ -n "$val" ] && uci set "dhcp.${sec}.filter_aaaa=$val"
	# If restore had nothing to put back, keep dnsmasq able to use WAN DNS.
	if [ "$has_server" = 0 ] && ! uci -q get "dhcp.${sec}.server" >/dev/null; then
		uci -q delete "dhcp.${sec}.noresolv"
	fi
	uci commit dhcp
	rm -f "$orig"
	"$DNSMASQ_INIT" restart
}
