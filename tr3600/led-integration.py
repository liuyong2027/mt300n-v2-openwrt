#!/usr/bin/env python3
"""Add bounded, best-effort LED observations without altering probe decisions."""
from pathlib import Path
import sys

def patch_probe(source):
    assert 'cudy_led_token' not in source, 'LED probe hook already installed'
    anchor='pid_start=$(pidof xray 2>/dev/null)\n'
    assert source.count(anchor)==1
    source=source.replace(anchor,'cudy_led_token=$(/usr/libexec/timeout-coreutils 2 /usr/libexec/cudy-led-control begin 2>/dev/null) || cudy_led_token=\n'+anchor)
    for old,code in [('write_log ok || :; exit 0','0'),('write_log failed || :\nexit 1','1')]:
        assert source.count(old)==1
        new='/usr/libexec/timeout-coreutils 2 /usr/libexec/cudy-led-control finish "$cudy_led_token" '+code+' >/dev/null 2>&1 || :; '+old
        source=source.replace(old,new)
    return source

def patch_upgrade(source):
    assert 'cudy-led-upgrade' not in source, 'LED upgrade hook already installed'
    anchor='v "Commencing upgrade. Closing all shell sessions."\n'
    assert source.count(anchor)==1
    source=source.replace(anchor,anchor+'[ ! -x /usr/libexec/cudy-led-upgrade ] || /usr/libexec/cudy-led-upgrade suspend >/dev/null 2>&1 || :\n')
    anchor='\tubus call system sysupgrade "$(json_dump)"\n'
    assert source.count(anchor)==1
    source=source.replace(anchor,anchor+'''\tcudy_led_result=$?
\tif [ "$cudy_led_result" != 0 ]; then
\t\t[ ! -x /usr/libexec/cudy-led-upgrade ] || /usr/libexec/cudy-led-upgrade resume >/dev/null 2>&1 || :
\tfi
\texit "$cudy_led_result"
''')
    return source

if __name__=='__main__':
    tree=Path(sys.argv[1])
    probe=tree/'package/luci-app-mango-proxy/root/usr/libexec/mango-probe'
    upgrade=tree/'openwrt/package/base-files/files/sbin/sysupgrade'
    # prepare.sh uses the OpenWrt working directory; package sources were copied there.
    if not upgrade.exists(): upgrade=tree/'package/base-files/files/sbin/sysupgrade'
    patched_probe=patch_probe(probe.read_text(encoding='utf-8'))
    patched_upgrade=patch_upgrade(upgrade.read_text(encoding='utf-8'))
    probe.write_text(patched_probe,encoding='utf-8',newline='\n')
    upgrade.write_text(patched_upgrade,encoding='utf-8',newline='\n')
