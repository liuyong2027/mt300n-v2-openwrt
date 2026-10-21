#!/bin/sh
umask 077
mkdir -p /etc/ssrplus /var/lock
# A failed migration leaves this defaults script available for the next boot.
lua /usr/libexec/ssrplus-migrate || exit 1
/etc/init.d/xray disable 2>/dev/null || :
# Remove only symlinks belonging to the retired Mango services.
for service in mango_proxy mango_watchdog; do
    for link in /etc/rc.d/*"$service"; do
        [ -L "$link" ] || continue
        [ "$(readlink "$link")" = "../init.d/$service" ] && rm -f "$link"
    done
done
/etc/init.d/shadowsocksr enable
/etc/init.d/ssrplus-direct-socks enable
exit 0
