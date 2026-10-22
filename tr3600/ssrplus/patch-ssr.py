"""Patch only the pinned SSR service's lifecycle, before kernel/package build."""
from pathlib import Path
import re
import sys
root=Path(sys.argv[1])
p=root/'feeds/helloworld/xray-core/Makefile'
s=p.read_text()
anchor='\tpython3 $(PKG_BUILD_DIR)/tools/eip93/overlay.py --go $(STAGING_DIR_HOSTPKG)/bin/go --out $(PKG_BUILD_DIR)/.eip93-overlay'
assert s.count(anchor)==1,'Pinned Xray overlay command changed'
s=s.replace(anchor,'\t$(GO_BIN_PATH) python3 $(PKG_BUILD_DIR)/tools/eip93/overlay.py --go go --out $(PKG_BUILD_DIR)/.eip93-overlay')
p.write_text(s,newline='\n')
p=root/'feeds/helloworld/luci-app-ssr-plus/root/etc/init.d/shadowsocksr'
s=p.read_text()
for name in ('start','stop'):
    pattern=r'^'+name+r'\(\) \{'
    assert len(re.findall(pattern,s,re.M))==1,name
    s=re.sub(pattern,name+'_without_cudy_gate() {',s,flags=re.M)
s+="""
# Cudy SS only uses this lifecycle gate; it has no independent upstream policy.
stop() {
    /usr/libexec/cudy-ss-gate close || return 1
    stop_without_cudy_gate "$@"
}
start() {
    /usr/libexec/cudy-ss-gate close || return 1
    start_without_cudy_gate "$@"
    cudy_result=$?
    if [ "$cudy_result" = 0 ]; then
        /usr/libexec/cudy-ss-ssr-interfaces || return 1
        /usr/libexec/cudy-ss-gate started || return 1
    fi
    return "$cudy_result"
}
"""
p.write_text(s,newline='\n')
rules=root/'feeds/helloworld/luci-app-ssr-plus/root/usr/bin/ssr-rules'
s=rules.read_text()
anchor='\tEOF\n\tchmod +x "$FWI"\n}'
assert s.count(anchor)==1,'Pinned nft include generator changed'
s=s.replace(anchor,'\t\t/usr/libexec/cudy-ss-ssr-interfaces\n'+anchor)
rules.write_text(s,newline='\n')

