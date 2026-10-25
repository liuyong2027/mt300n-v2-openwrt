#!/bin/sh
# Keep ordinary settings; explicitly delete the retired private SS identity.
set -eu
umask 077
[ "$(cat /tmp/sysinfo/board_name 2>/dev/null)" = cudy,tr3600-v1 ] || exit 0
mkdir -p /etc/cudy-ss /etc/cudy-ssrplus /var/lock
chmod 700 /etc/cudy-ss /etc/cudy-ssrplus
if [ ! -s /etc/config/shadowsocksr ]; then
    cp /usr/share/shadowsocksr/shadowsocksr.config /etc/config/shadowsocksr
    touch /etc/cudy-ssrplus/seeded-config
fi
# Mango client migration remains useful for upgrades from the original firmware.
# This helper does not migrate the old private SS credentials.
lua /usr/lib/cudy-ss/migrate.lua
lua -e "dofile('/usr/lib/cudy-ss/remove-private.lua').run()"
for service in mango_proxy mango_watchdog; do
    for link in /etc/rc.d/S*"$service" /etc/rc.d/K*"$service"; do
        [ -L "$link" ] || continue
        [ "$(readlink "$link")" = "../init.d/$service" ] && rm -f "$link"
    done
done
/usr/libexec/cudy-ss-gate close
/etc/init.d/shadowsocksr enable
/etc/init.d/xray disable 2>/dev/null || :
