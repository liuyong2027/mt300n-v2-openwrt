#!/usr/bin/env python3
"""Add bounded lifecycle hooks to the exact locked ZeroTier init script."""
import hashlib
from pathlib import Path
import sys

def patch(source):
    raw=source.encode()
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()=='01aff425f37cf212cae6dd2da3ae7461f8d164a5', 'Unexpected locked ZeroTier init'
    start='start_service() {\n\tconfig_load zerotier\n'
    stop='stop_service() {\n'
    hook='\t/usr/libexec/cudy-zt-direct || logger -t cudy-zt-direct "Direct-path firewall update deferred"\n'
    assert source.count(start)==1 and source.count(stop)==1
    return source.replace(start,start+hook).replace(stop,stop+hook)

if __name__=='__main__':
    path=Path(sys.argv[1])/'feeds/packages/net/zerotier/files/etc/init.d/zerotier'
    path.write_text(patch(path.read_text()),newline='\n')
