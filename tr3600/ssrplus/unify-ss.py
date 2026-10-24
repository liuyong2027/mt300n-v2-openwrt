#!/usr/bin/env python3
"""Replace the legacy private runtime with shared, scoped ordinary SS servers."""
from pathlib import Path
import shutil
import sys

HERE=Path(__file__).resolve().parent

def once(text,old,new):
    assert text.count(old)==1,repr(old[:120])
    return text.replace(old,new,1)

def patch(root):
    runtime=root/'package/luci-app-cudy-ss'
    package=root/'feeds/helloworld/luci-app-ssr-plus'
    files={}
    path=package/'luasrc/model/cbi/shadowsocksr/server-config.lua'
    s=path.read_text(encoding='utf-8')
    begin=s.index('function o.validate(self, value, section)\n')
    end=s.index('\nend',begin)+4
    s=s[:begin]+s[end:]
    begin=s.index('local cudy_ss_model =')
    end=s.index('\no.default = "chacha20-ietf-poly1305"',begin)
    s=s[:begin]+'''local cudy_ss_model = require('cudy.ssr-server')
for _, v in ipairs(v_ss_encrypt_method_list) do o:value(v) end'''+s[end:]
    begin=s.index("    if cudy_ss_private and value ~=")
    end=s.index('    local valid, result = pcall',begin)
    s=s[:begin]+s[end:]
    begin=s.index('-- Actual server exposure is enforced')
    end=s.index('o = s:option(ListValue, "naive_alpn",',begin)
    s=s[:begin]+(HERE/'unified-access-ui.lua').read_text(encoding='utf-8')+'\n'+s[end:]
    assert 'cudy_zt_' not in s and 'cudy_ss_private' not in s
    files[path]=s
    path=package/'luasrc/model/cbi/shadowsocksr/server.lua'
    s=path.read_text(encoding='utf-8')
    s=once(s,"    if require('cudy.ssr-server').private(raw) then return translate('Approved ZeroTier only') end\n",'')
    files[path]=s
    path=package/'luasrc/model/cbi/shadowsocksr/status.lua'
    s=path.read_text(encoding='utf-8')
    begin=s.index('if Process_list:find("ssr.server") or Process_list:find("/xray%-server%-%d+") then')
    end=s.index('\nend',s.index('if cudy_private_requested',begin))+4
    s=s[:begin]+(HERE/'server-status.lua').read_text(encoding='utf-8').rstrip()+s[end:]
    files[path]=s
    path=package/'root/etc/init.d/shadowsocksr'
    s=path.read_text(encoding='utf-8')
    begin=s.index('        # Never fall back to a host listener')
    end=s.index('\t\t[ "$(uci_get_by_name "$1" enable 0)"',begin)
    s=s[:begin]+s[end:]
    anchor='\t\t/usr/libexec/cudy-ssr-server-rules validate "$1" || return 1\n'
    s=once(s,anchor,anchor+'''        if [ "$(uci_get_by_name "$1" type)" = shadowsocks ]; then
            # cudy_ss owns these inbounds, including UDP, after SSR policy starts.
            return 0
        fi
''')
    begin=s.index('        shadowsocks)\n',s.index('start_server() {'))
    end=s.index('\t\tvmess|vless|trojan)',begin)
    s=s[:begin]+s[end:]
    # Preserve the complete upstream entry conditions (proxy ports, source ACL,
    # bypasses and mode), rather than jumping directly into a business chain.
    s=once(s,'-m "$(uci_get_by_type access_control Interface)"', '-m "$(cudy_ss_client_interfaces)"')
    s+='''
cudy_ss_client_interfaces() {
    local interfaces
    interfaces="$(uci_get_by_type access_control Interface)"
    # Empty means all interfaces in upstream SSR and must retain that meaning.
    case " $interfaces " in
        *" cudy_ss "*|"  ") printf '%s' "$interfaces" ;;
        *) printf '%s cudy_ss' "$interfaces" ;;
    esac
}
'''
    files[path]=s
    model=runtime/'root/usr/lib/lua/cudy/ssr-server.lua'
    s=model.read_text(encoding='utf-8')
    s=once(s,'return M\n',(HERE/'unified-model.lua').read_text(encoding='utf-8')+'\nreturn M\n')
    s=s.replace('ZeroTier private server must use the approved namespace runtime','Retired private SS configuration must be removed')
    files[model]=s
    gate=runtime/'root/usr/libexec/cudy-ss-gate'
    s=gate.read_text(encoding='utf-8').replace('priority -312','priority -191')
    s=once(s,'nft -c -f "$temp"', '''# Avoid rewriting flash and the ruleset on every healthy watcher pass.
if cmp -s "$temp" /etc/cudy-ss/route-guard.nft && nft list table inet cudy_ss_gate >/dev/null 2>&1; then exit 0; fi
nft -c -f "$temp"''')
    files[gate]=s
    # Resolve every pinned anchor before changing any installed source.
    for path,s in files.items():path.write_text(s,encoding='utf-8',newline='\n')
    shutil.copytree(HERE/'unified-root',runtime/'root',dirs_exist_ok=True)
    for relative in ('etc/config/cudy_ss','usr/lib/cudy-ss/config.lua','usr/lib/cudy-ss/ss-zt.lua',
        'usr/lib/cudy-ss/ss-server-migrate.lua','usr/libexec/cudy-ss-zt',
        'usr/libexec/cudy-ss-zt-watch','usr/libexec/cudy-ss-zt-guard','lib/upgrade/keep.d/cudy-ss'):
        (runtime/'root'/relative).unlink()
    for relative in ('etc/uci-defaults/95-cudy-ss',):
        (runtime/'root'/relative).write_text("#!/bin/sh\nset -eu\nlua -e \"dofile('/usr/lib/cudy-ss/remove-private.lua').run()\"\n# SSR owns startup; avoid a second rcS start of the shared core.\n/etc/init.d/cudy_ss disable\n/etc/init.d/cudy_ss_core disable\n",encoding='utf-8',newline='\n')
    migration=root/'files/etc/uci-defaults/90-cudy-ssrplus-migrate'
    shutil.copyfile(HERE/'unified-migration.sh',migration)
    makefile=runtime/'Makefile'
    s=makefile.read_text(encoding='utf-8').replace('SSR Plus+ private ZeroTier server runtime','SSR Plus+ scoped Shadowsocks server runtime')
    makefile.write_text(s,encoding='utf-8',newline='\n')
    generator=runtime/'root/usr/share/shadowsocksr/gen_cudy_ss_server.lua'
    generator.write_text('''#!/usr/bin/lua
local json=require('luci.jsonc')
local runtime=dofile('/usr/lib/cudy-ss/server-runtime.lua')
io.write(json.stringify(runtime.config())..'\\n')
''',encoding='utf-8',newline='\n')
    for path in (runtime/'root').rglob('*'):
        if path.is_file() and path.read_bytes().startswith(b'#!'):path.chmod(path.stat().st_mode|0o111)
    migration.chmod(migration.stat().st_mode|0o111)

if __name__=='__main__':patch(Path(sys.argv[1]))
