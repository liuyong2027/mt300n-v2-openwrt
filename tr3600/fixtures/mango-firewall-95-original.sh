#!/bin/sh
uci -q batch <<'EOF'
set firewall.mango_proxy=include
set firewall.mango_proxy.type='script'
set firewall.mango_proxy.path='/usr/libexec/mango-fw'
set firewall.mango_proxy.fw4_compatible='1'
set firewall.mango_zt=zone
set firewall.mango_zt.name='mangozt'
add_list firewall.mango_zt.device='zt+'
set firewall.mango_zt.input='ACCEPT'
set firewall.mango_zt.output='ACCEPT'
set firewall.mango_zt.forward='REJECT'
set firewall.mango_zt.masq='1'
delete firewall.mango_zt.masq_src
delete firewall.mango_zt.masq_dest
set firewall.mango_lan_zt=forwarding
set firewall.mango_lan_zt.src='lan'
set firewall.mango_lan_zt.dest='mangozt'
set firewall.mango_mark=rule
set firewall.mango_mark.name='Mango transparent input'
set firewall.mango_mark.src='*'
set firewall.mango_mark.proto='tcp udp'
set firewall.mango_mark.mark='0x100/0xffffffff'
set firewall.mango_mark.family='ipv4'
set firewall.mango_mark.target='ACCEPT'
set firewall.mango_zt_dns=rule
set firewall.mango_zt_dns.name='Mango ZeroTier DNS'
set firewall.mango_zt_dns.src='mangozt'
set firewall.mango_zt_dns.proto='tcp udp'
set firewall.mango_zt_dns.dest_port='53'
set firewall.mango_zt_dns.family='ipv4'
set firewall.mango_zt_dns.target='ACCEPT'
set firewall.mango_zt_dns.enabled='1'
set firewall.mango_zt_wan=rule
set firewall.mango_zt_wan.name='Mango ZeroTier IPv4 gateway'
set firewall.mango_zt_wan.src='mangozt'
set firewall.mango_zt_wan.dest='wan'
set firewall.mango_zt_wan.proto='all'
set firewall.mango_zt_wan.family='ipv4'
set firewall.mango_zt_wan.target='ACCEPT'
set firewall.mango_zt_wan.enabled='1'
delete firewall.mango_zt_dns.src_ip
delete firewall.mango_zt_wan.src_ip
commit firewall
EOF
/etc/init.d/xray stop 2>/dev/null
/etc/init.d/xray disable 2>/dev/null
/etc/init.d/mango_proxy enable
# rc.common disable only removes S?? names, so explicitly migrate the old S100 link.
if [ "$(readlink /etc/rc.d/S100mango_watchdog 2>/dev/null)" = '../init.d/mango_watchdog' ]; then
    rm -f /etc/rc.d/S100mango_watchdog
fi
/etc/init.d/mango_watchdog enable
exit 0
