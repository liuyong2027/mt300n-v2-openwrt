#!/bin/sh
# Idempotent firewall defaults for already-flashed Release 25 IKEv2 images.
# Does not touch VPN credentials or lan_device.
set -eu

uci -q delete firewall.mangozt
uci set firewall.mangozt=zone
uci set firewall.mangozt.name='mangozt'
uci set firewall.mangozt.input='ACCEPT'
uci set firewall.mangozt.output='ACCEPT'
uci set firewall.mangozt.forward='REJECT'
uci set firewall.mangozt.masq='1'
uci set firewall.mangozt.mtu_fix='1'
uci set firewall.mangozt.device='zt+'

if ! uci -q show firewall | grep -q "dest='mangozt'"; then
	idx=$(uci add firewall forwarding)
	uci set "firewall.$idx.src=lan"
	uci set "firewall.$idx.dest=mangozt"
fi

uci -q delete firewall.zt_to_wan
uci set firewall.zt_to_wan=forwarding
uci set firewall.zt_to_wan.src='mangozt'
uci set firewall.zt_to_wan.dest='wan'

uci -q delete firewall.allow_zt_udp
uci set firewall.allow_zt_udp=rule
uci set firewall.allow_zt_udp.name='Allow-ZeroTier-Direct'
uci set firewall.allow_zt_udp.src='wan'
uci set firewall.allow_zt_udp.proto='udp'
uci set firewall.allow_zt_udp.dest_port='9993'
uci set firewall.allow_zt_udp.target='ACCEPT'

uci commit firewall
/etc/init.d/firewall reload
echo "OK: mangozt + Allow-ZeroTier-Direct applied"
