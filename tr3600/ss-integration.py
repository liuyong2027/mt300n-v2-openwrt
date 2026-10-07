#!/usr/bin/env python3
"""Add private SS to the existing core; preserve exact original entry points."""
from pathlib import Path
import sys

WRAPPERS={
    'usr/libexec/mango-generate':'''#!/bin/sh
if [ "$1" = json ]; then
    /usr/libexec/mango-generate.cudy-ss-base "$@" | /usr/libexec/cudy-ss-zt augment
else
    exec /usr/libexec/mango-generate.cudy-ss-base "$@"
fi
''',
    'usr/libexec/mango-ready':'''#!/bin/sh
/usr/libexec/mango-ready.cudy-ss-base "$@" || exit $?
exec /usr/libexec/cudy-ss-zt ready
'''
}
def patch_init(text):
    anchor='[ "$(uci -q get mango_proxy.main.socks_server)" = 1 ]'
    assert text.count(anchor)==1 and 'cudy_ss.main.enabled' not in text
    return text.replace(anchor,anchor+' ||\n        [ "$(uci -q get cudy_ss.main.enabled)" = 1 ]')

def install(tree):
    root=Path(tree)/'package/luci-app-mango-proxy/root'
    for name,wrapper in WRAPPERS.items():
        file=root/name;backup=root/(name+'.cudy-ss-base')
        assert file.is_file() and not backup.exists(),name
        backup.write_bytes(file.read_bytes());backup.chmod(0o755)
        file.write_text(wrapper,encoding='utf-8',newline='\n');file.chmod(0o755)
    init=root/'etc/init.d/mango_proxy'
    init.write_text(patch_init(init.read_text(encoding='utf-8')),encoding='utf-8',newline='\n')

if __name__=='__main__': install(sys.argv[1])
