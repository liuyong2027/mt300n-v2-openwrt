#!/bin/sh /etc/rc.common
START=96
STOP=14
USE_PROCD=1
start_service() {
    [ "$(uci -q get shadowsocksr.@global[0].global_server)" = nil ] || return 0
    [ "$(uci -q get shadowsocksr.@global[0].mango_direct_socks)" = 1 ] || return 0
    local port
    port=$(uci -q get shadowsocksr.@socks5_proxy[0].local_port)
    case "$port" in ''|*[!0-9]*) return 1 ;; esac
    [ "$port" -ge 1024 ] && [ "$port" -le 65535 ] || return 1
    mkdir -p /var/etc/ssrplus
    cat > /var/etc/ssrplus/direct-socks.json <<EOF
{"log":{"loglevel":"warning"},"inbounds":[{"listen":"0.0.0.0","port":$port,"protocol":"socks","settings":{"auth":"noauth","udp":false}}],"outbounds":[{"protocol":"freedom","settings":{"domainStrategy":"UseIPv4"}}]}
EOF
    procd_open_instance
    procd_set_param command /usr/bin/xray run -config /var/etc/ssrplus/direct-socks.json
    procd_set_param env GOMEMLIMIT=48MiB GOMAXPROCS=1
    procd_set_param respawn 3600 5 3
    procd_close_instance
}
service_triggers() {
    procd_add_reload_trigger shadowsocksr
}
