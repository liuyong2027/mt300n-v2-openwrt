#!/usr/bin/env python3
"""Add bounded, best-effort LED observations without altering probe decisions."""
from pathlib import Path
import sys

PROBE_SOURCE_SHA256='a2582dd3f23951946269ca5feaa9aeaa1651acf5f395a788be4905e6e6c07c07'
def patch_probe(source):
    import hashlib
    assert hashlib.sha256(source.encode()).hexdigest()==PROBE_SOURCE_SHA256, 'Unexpected original Mango probe; refusing replacement'
    return (Path(__file__).resolve().parent/'led-probe/mango-probe').read_text(encoding='utf-8')

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
    common=probe.with_name('mango-connectivity-probe')
    common.write_bytes((Path(__file__).resolve().parent/'led-probe/mango-connectivity-probe').read_bytes())
    common.chmod(0o755)
    upgrade.write_text(patched_upgrade,encoding='utf-8',newline='\n')
