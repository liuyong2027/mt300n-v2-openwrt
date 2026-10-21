#!/bin/sh
# Settings migration runs before the retired firewall include can be evaluated.
set -eu
umask 077
[ "$(cat /tmp/sysinfo/board_name 2>/dev/null)" = cudy,tr3600-v1 ] || exit 0
mkdir -p /etc/cudy-ss /etc/cudy-ssrplus /var/lock
chmod 700 /etc/cudy-ss /etc/cudy-ssrplus
# Retain a private, owner-readable copy of old configuration for manual rollback.
for name in mango_proxy dhcp firewall; do
    if [ -f "/etc/config/$name" ] && [ ! -f "/etc/cudy-ssrplus/$name.before-migration" ]; then
        cp -p "/etc/config/$name" "/etc/cudy-ssrplus/$name.before-migration"
        chmod 600 "/etc/cudy-ssrplus/$name.before-migration"
    fi
done
if [ ! -s /etc/config/shadowsocksr ]; then
    cp /usr/share/shadowsocksr/shadowsocksr.config /etc/config/shadowsocksr
    touch /etc/cudy-ssrplus/seeded-config
fi
lua /usr/lib/cudy-ss/migrate.lua
uci -q batch <<'UCI'
set network.cudy_ss=interface
set network.cudy_ss.proto='none'
set network.cudy_ss.device='css-host'
commit network
UCI
# Old init scripts and binaries are not copied into the new image. These are
# only stale rcS links and a known legacy marker, never user firewall sections.
for service in mango_proxy mango_watchdog; do
    for link in /etc/rc.d/S*"$service" /etc/rc.d/K*"$service"; do
        [ -L "$link" ] || continue
        [ "$(readlink "$link")" = "../init.d/$service" ] && rm -f "$link"
    done
done
# The namespace is the only additional routed client.
uci -q batch <<'UCI'
set firewall.cudy_ss=zone
set firewall.cudy_ss.name='cudyss'
add_list firewall.cudy_ss.device='css-host'
set firewall.cudy_ss.input='ACCEPT'
set firewall.cudy_ss.output='ACCEPT'
set firewall.cudy_ss.forward='REJECT'
set firewall.cudy_ss_to_wan=forwarding
set firewall.cudy_ss_to_wan.src='cudyss'
set firewall.cudy_ss_to_wan.dest='wan'
set firewall.cudy_ss_to_lan=forwarding
set firewall.cudy_ss_to_lan.src='cudyss'
set firewall.cudy_ss_to_lan.dest='lan'
set firewall.cudy_ss_to_zt=forwarding
set firewall.cudy_ss_to_zt.src='cudyss'
set firewall.cudy_ss_to_zt.dest='mangozt'
set firewall.cudy_zt_to_ss=forwarding
set firewall.cudy_zt_to_ss.src='mangozt'
set firewall.cudy_zt_to_ss.dest='cudyss'
set firewall.cudy_ss_route_guard=include
set firewall.cudy_ss_route_guard.type='nftables'
set firewall.cudy_ss_route_guard.position='ruleset-pre'
set firewall.cudy_ss_route_guard.path='/etc/cudy-ss/route-guard.nft'
set firewall.cudy_zt_ipv6_guard=rule
set firewall.cudy_zt_ipv6_guard.src='mangozt'
set firewall.cudy_zt_ipv6_guard.dest='*'
set firewall.cudy_zt_ipv6_guard.family='ipv6'
set firewall.cudy_zt_ipv6_guard.target='DROP'
commit firewall
UCI
/usr/libexec/cudy-ss-gate close
/etc/init.d/shadowsocksr enable
# Never enable the package's generic Xray service alongside SSR Plus+.
/etc/init.d/xray disable 2>/dev/null || :

