#!/bin/sh
# Sourced only by the standard ddns-scripts send_update function.
local cudy_hosts cudy_host cudy_url cudy_result
local cudy_curl="$CURL"
local LUCI_HELPER=1
local USE_CURL=1
local CURL="$CURL"
[ "${use_ipv6:-0}" = 0 ] && [ "${use_https:-0}" = 1 ] || return 1
[ -n "$URL_USER" ] && [ -n "$URL_PASS" ] && [ -n "$domain" ] || return 1
case "$domain" in *[!A-Za-z0-9.-]*|'') return 1;; esac
/usr/libexec/cudy-dynu-resolve --public-ip "$__IP" || return 1
cudy_hosts=$(/usr/libexec/cudy-dynu-resolve) || {
    write_log 3 'Dynu encrypted DNS lookup failed; no update sent'
    return 1
}
cudy_url="https://api.dynu.com/nic/update?hostname=$domain&myip=$__IP&myipv6=no&username=$URL_USER&password=$URL_PASS"
for cudy_host in $cudy_hosts; do
    CURL="$cudy_curl --resolve api.dynu.com:443:$cudy_host --connect-timeout 4 --max-time 10"
    if do_transfer "$cudy_url"; then
        if grep -E -q '^(good|nochg)([[:space:]]|$)' "$DATFILE"; then
            return 0
        fi
        # A valid HTTPS response with a provider error is not retried on other
        # addresses, avoiding repeated authentication requests for bad settings.
        write_log 3 'Dynu rejected the HTTPS update; inspect provider response status'
        return 1
    fi
done
write_log 3 'Dynu HTTPS connection failed for all verified DNS answers'
return 1
