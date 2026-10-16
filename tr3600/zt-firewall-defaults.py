#!/usr/bin/env python3
"""Preserve configured Mango firewall sections during a settings upgrade."""
import hashlib
from pathlib import Path
import re
import sys

BASE_SHA256 = 'b4ed3392155deb6e679a017cd9d7f820219a67c1ff7809b3bd6c874f1928f2e8'
SECTIONS = ('mango_proxy','mango_zt','mango_lan_zt','mango_mark','mango_zt_dns','mango_zt_wan')

def patch(source):
    assert hashlib.sha256(source.encode()).hexdigest()==BASE_SHA256, 'Unexpected locked Mango firewall defaults'
    prefix="#!/bin/sh\nuci -q batch <<'EOF'\n"
    assert source.startswith(prefix)
    body,tail=source[len(prefix):].split('\nEOF\n',1)
    groups={s:[] for s in SECTIONS}
    for line in body.splitlines():
        if not line or line=='commit firewall': continue
        match=re.match(r'(?:set|add_list|delete) firewall\.([a-z_]+)(?:[.=])',line)
        assert match and match[1] in groups,line
        groups[match[1]].append(line)
    # User-selected fresh-install policy. Existing owner sections stay intact.
    old="set firewall.mango_zt.forward='REJECT'"
    assert groups['mango_zt'].count(old)==1
    groups['mango_zt']=["set firewall.mango_zt.forward='ACCEPT'" if line==old else line for line in groups['mango_zt']]
    out=['#!/bin/sh','# Existing owner policies, restrictions and disabled rules take precedence.']
    for name in SECTIONS:
        assert groups[name][0].startswith('set firewall.'+name+'=')
        out += ["if ! uci -q get firewall."+name+" >/dev/null; then", "uci -q batch <<'EOF'"]+groups[name]+['EOF','fi']
    out += ['uci -q commit firewall',tail.rstrip('\n')]
    return '\n'.join(out)+'\n'

if __name__=='__main__':
    path=Path(sys.argv[1])/'package/luci-app-mango-proxy/root/etc/uci-defaults/95-mango-proxy'
    path.write_text(patch(path.read_text()),newline='\n')
