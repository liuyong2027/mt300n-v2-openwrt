#!/usr/bin/env python3
"""Prepare an isolated SSR Plus+ build from the pinned TR3600 1.1.1 recipe."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
PROFILE=Path(__file__).resolve().parent
SSR_COMMIT='80d7bfff625b33db8afe80934638d96d214ceadc'

def replace(path,old,new,count=1):
    text=path.read_text(encoding='utf-8')
    if text.count(old)!=count:
        raise ValueError(f'Unexpected source: {path}: {old[:100]!r}')
    path.write_text(text.replace(old,new),encoding='utf-8',newline='\n')

def prepare():
    spec=importlib.util.spec_from_file_location('tr3600_port',ROOT/'tr3600/port.py')
    port=importlib.util.module_from_spec(spec);spec.loader.exec_module(port)
    port.extract();port.adapt()
    # Keep device support and other Cudy applications; no Mango package is installed.
    p=ROOT/'scripts/prepare.sh'
    text=p.read_text(encoding='utf-8')
    start=text.index('cp -R "$kit/package/luci-app-mango-proxy" package/')
    end=text.index('cp -R "$kit/files" .',start)
    text=text[:start]+'''cp -R "$kit/tr3600/luci-app-cudy-wifi" package/
cp -R "$kit/tr3600/luci-app-cudy-led" package/
cp -R "$kit/tr3600/luci-app-cudy-usb" package/
cp -R "$kit/tr3600/luci-app-cudy-ss" package/
cp -R "$kit/tr3600/cudy-webfiles" package/
cp -R "$kit/tr3600/luci-app-cudy-webfiles" package/
cp -R "$kit/tr3600/ssrplus/cudy-ddns-direct" package/
python3 "$kit/tr3600/usb-integration.py" "$PWD"
find package/luci-app-cudy-* package/cudy-webfiles -type f -exec sh -c 'head -c 2 "$1" | grep -q "#!" && chmod +x "$1" || :' sh {} \\;
'''+text[end:]
    # Source package dependency resolution uses this exact feed, including its Xray.
    text=text.replace('./scripts/feeds update -a','printf \'%s\\n\' \'src-git helloworld https://github.com/fw876/helloworld.git^'+SSR_COMMIT+'\' >> feeds.conf.default\n./scripts/feeds update -a')
    # Install selected helloworld packages first: -f does not replace a package
    # already linked from another feed. The following -a preserves these links.
    text=text.replace('./scripts/feeds install -a', '''git clone --depth 1 --no-checkout --filter=blob:none https://github.com/openwrt/packages.git "$kit/work-go-feed"
git -C "$kit/work-go-feed" sparse-checkout set lang/golang
git -C "$kit/work-go-feed" fetch --depth 1 origin 2a5d2301904f84ff61615dd4e4d1db6d4f1fbf67
git -C "$kit/work-go-feed" checkout --detach FETCH_HEAD
rm -rf feeds/packages/lang/golang
cp -R "$kit/work-go-feed/lang/golang" feeds/packages/lang/
./scripts/feeds update -i packages
./scripts/feeds install -f -p helloworld xray-core luci-app-ssr-plus dns2tcp lua-neturl ipt2socks
./scripts/feeds install -a
python3 "$kit/tr3600/ssrplus/patch-ssr.py" "$PWD"
python3 "$kit/tr3600/ssrplus/patch-ss-server.py" "$PWD"''')
    text=text.replace('chmod +x files/etc/board.d/99-mango-network', 'chmod +x files/etc/board.d/99-mango-network files/etc/uci-defaults/90-cudy-ssrplus-migrate')
    text=text.replace('cp -R "$kit/files" .', '''cp -R "$kit/files" .
python3 "$kit/tr3600/ssrplus/patch-ddns.py" --framework feeds/packages/net/ddns-scripts/files/usr/lib/ddns/dynamic_dns_functions.sh --resolver files/usr/libexec/cudy-dynu-resolve''')
    text=re.sub(r'^python3 "\$kit/scripts/build-profile.py".*\n','',text,flags=re.M)
    text=text.replace(' luci-app-mango-proxy','').replace(' mango-tcpcheck','')
    text=text.replace('! grep -qx \'CONFIG_PACKAGE_v2ray-geoip=y\' .config\n','').replace('! grep -qx \'CONFIG_PACKAGE_v2ray-geosite=y\' .config\n','')
    text=text.replace('cp "$kit/tr3600/tr3600.config" .config','cp "$kit/tr3600/ssrplus/tr3600.config" .config')
    p.write_text(text,encoding='utf-8',newline='\n')
    cfg=(ROOT/'tr3600/tr3600.config').read_text(encoding='utf-8')
    cfg=re.sub(r'^CONFIG_PACKAGE_(luci-app-mango-proxy|mango-tcpcheck)=y\n','',cfg,flags=re.M)
    cfg+='''\n# SSR Plus+ is the sole transparent proxy.
CONFIG_PACKAGE_luci-app-ssr-plus=y
CONFIG_PACKAGE_luci-app-ssr-plus_Nftables_Transparent_Proxy=y
# CONFIG_PACKAGE_luci-app-ssr-plus_Iptables_Transparent_Proxy is not set
CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Xray=y
# CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_NONE_V2RAY is not set
CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Shadowsocks_NONE_Client=y
# CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Http_Proxy is not set
# CONFIG_PACKAGE_luci-app-ssr-plus_INCLUDE_Mihomo is not set
# CONFIG_XRAY_CORE_NAIVE is not set
CONFIG_PACKAGE_luci-compat=y
CONFIG_PACKAGE_cudy-ddns-direct=y
CONFIG_PACKAGE_dnsmasq-full=y
CONFIG_PACKAGE_dnsmasq_full_nftset=y
# CONFIG_PACKAGE_dnsmasq is not set
CONFIG_PACKAGE_kmod-nft-socket=y
CONFIG_PACKAGE_kmod-veth=y
CONFIG_PACKAGE_v2ray-geoip=y
CONFIG_PACKAGE_v2ray-geosite=y
'''
    # Avoid duplicate "not set" entries overriding the selected data packages.
    cfg=cfg.replace('# CONFIG_PACKAGE_v2ray-geoip is not set\n','').replace('# CONFIG_PACKAGE_v2ray-geosite is not set\n','')
    (PROFILE/'tr3600.config').write_text(cfg,encoding='utf-8',newline='\n')
    ss=ROOT/'tr3600/luci-app-cudy-ss'
    replace(ss/'Makefile','+luci-app-mango-proxy','+xray-core +ip-full +kmod-veth')
    lib=ss/'root/usr/lib'
    (lib/'cudy-ss').mkdir()
    for name in ('ss-zt.lua','ss-transaction.lua'):
        shutil.move(str(lib/'mango'/name),str(lib/'cudy-ss'/name))
    (lib/'mango').rmdir()
    shutil.copy2(PROFILE/'config.lua',lib/'cudy-ss/config.lua')
    shutil.copy2(PROFILE/'ss-server-migrate.lua',lib/'cudy-ss/ss-server-migrate.lua')
    for path in (ss/'root').rglob('*'):
        if not path.is_file():continue
        s=path.read_text(encoding='utf-8')
        s=s.replace('/usr/lib/mango/','/usr/lib/cudy-ss/').replace('MANGO_OPERATION_LOCK','CUDY_SS_OPERATION_LOCK')
        s=s.replace('/var/lock/mango-operation.lock','/var/lock/cudy-ss-operation.lock').replace('/usr/libexec/mango-lock','/usr/libexec/cudy-ss-lock')
        path.write_text(s,encoding='utf-8',newline='\n')
    model=lib/'cudy-ss/ss-zt.lua'
    replace(model,'found.listen==c.listen','found.listen=="0.0.0.0"')
    # The UI and runtime use exactly the same original private credential rules.
    replace(model, '''function M.validate(raw)
    if not raw or raw.enabled~='1' then return nil end
    local c=M.scope(raw)
    local port=tonumber(raw.port)
    assert(port and port==math.floor(port) and port>=1024 and port<=65535 and not ({[1053]=true,[10808]=true,[10809]=true,[10810]=true,[12345]=true})[port],'Invalid or reserved port')
    assert(raw.method=='aes-128-gcm' or raw.method=='aes-256-gcm' or raw.method=='chacha20-ietf-poly1305','An authenticated SS cipher is required')
    assert(type(raw.password)=='string' and #raw.password>=24 and #raw.password<=128 and not raw.password:find('[%c]'),'A strong generated password is required')
    c.port=port; c.method=raw.method; c.password=raw.password
    return c
end''', '''function M.private_port(value)
    local port=tonumber(value)
    assert(port and port==math.floor(port) and port>=1024 and port<=65535 and not ({[1053]=true,[10808]=true,[10809]=true,[10810]=true,[12345]=true})[port],'Invalid or reserved port')
    return port
end
function M.private_credentials(raw,allow_empty_password)
    local port=M.private_port(raw.port)
    assert(raw.method=='aes-128-gcm' or raw.method=='aes-256-gcm' or raw.method=='chacha20-ietf-poly1305','An authenticated SS cipher is required')
    if not allow_empty_password or (raw.password~=nil and raw.password~='') then
        assert(type(raw.password)=='string' and #raw.password>=24 and #raw.password<=128 and not raw.password:find('[%c]'),'A strong generated password is required')
    end
    return {port=port,method=raw.method,password=raw.password}
end
function M.validate(raw)
    if not raw or raw.enabled~='1' then return nil end
    local c=M.scope(raw)
    local credentials=M.private_credentials(raw)
    c.port=credentials.port; c.method=credentials.method; c.password=credentials.password
    return c
end''')
    # Keep existing validation, approval scope and transaction logic.
    s=model.read_text(encoding='utf-8')
    s=s.replace('function M.guard(c)\n', 'function M.legacy_guard(c)\n')
    s=s.replace('function M.bridge(old,candidate)\n','function M.legacy_bridge(old,candidate)\n')
    s=s.replace('return M\n',"""local N=dofile('/usr/lib/cudy-ss/config.lua')
M.guard=N.guard
M.matches=N.matches
M.bridge=function(old,new) return N.bridge(M.validate(old),M.validate(new)) end
return M
""")
    model.write_text(s,encoding='utf-8',newline='\n')
    worker=ss/'root/usr/libexec/cudy-ss-worker'
    s=worker.read_text(encoding='utf-8').replace('/var/etc/mango/config.json','/var/etc/cudy-ss/config.json')
    s=s.replace('/usr/libexec/mango-process','/usr/libexec/cudy-ss-process')
    s=s.replace("CUDY_SS_UI_TRANSACTION=1 CUDY_SS_OPERATION_LOCK=1 MANGO_APPLY_WORKER=1 /etc/init.d/mango_proxy reload",
                "CUDY_SS_UI_TRANSACTION=1 CUDY_SS_OPERATION_LOCK=1 /etc/init.d/cudy_ss_core restart")
    s=s.replace("command('CUDY_SS_UI_TRANSACTION=1 CUDY_SS_OPERATION_LOCK=1 /usr/libexec/mango-ready') and\n        ",'')
    s=s.replace("local core=assert(j.parse(capture('/usr/libexec/mango-generate.cudy-ss-base json')))\n        M.augment(core,validated(r),r.enabled=='1')",
                "local core=dofile('/usr/lib/cudy-ss/config.lua').config(assert(M.validate(setmetatable({enabled='1'},{__index=r}))))")
    s=s.replace("command('/usr/libexec/mango-preflight '..quote(stage..'/candidate.json'))",
                "command('/usr/bin/xray run -test -config '..quote(stage..'/candidate.json'))")
    # Disabled never-configured services need no arbitrary credential or namespace.
    s=s.replace("local core=dofile", "if r.enabled~='1' then return true end\n        local core=dofile")
    worker.write_text(s,encoding='utf-8',newline='\n')
    shutil.copytree(PROFILE/'root',ss/'root',dirs_exist_ok=True)
    # Private SS is an SSR Plus+ server row. Retain the internal namespace
    # runtime but remove the second management API and its legacy write path.
    for relative in (
        'usr/share/luci/menu.d/luci-app-cudy-ss.json',
        'usr/share/rpcd/acl.d/luci-app-cudy-ss.json',
        'usr/libexec/rpcd/cudy.ss', 'usr/libexec/cudy-ss-worker',
        'usr/libexec/cudy-ss-job', 'usr/lib/cudy-ss/ss-transaction.lua',
    ):
        (ss/'root'/relative).unlink()
    shutil.rmtree(ss/'htdocs')
    replace(ss/'Makefile', 'Cudy private ZeroTier Shadowsocks server',
        'SSR Plus+ private ZeroTier server runtime')
    defaults=ss/'root/etc/uci-defaults/95-cudy-ss'
    defaults.write_text((PROFILE/'ss-server-defaults.sh').read_text(encoding='utf-8'),
        encoding='utf-8',newline='\n')
    # Independent ZeroTier firewall defaults, preserving existing owner sections.
    replace(ROOT/'tr3600/zt-firewall-defaults.py',
        "path=Path(sys.argv[1])/'package/luci-app-mango-proxy/root/etc/uci-defaults/95-mango-proxy'",
        "path=Path(sys.argv[1])/'package/luci-app-cudy-ss/root/etc/uci-defaults/94-cudy-zt-zone'")
    base=ROOT/'package/luci-app-mango-proxy/root/etc/uci-defaults/95-mango-proxy'
    source=base.read_text(encoding='utf-8')
    # This script is first generated, then passed through the original ownership patch.
    (ss/'root/etc/uci-defaults/94-cudy-zt-zone').write_text(source,encoding='utf-8',newline='\n')
    # Its output must not reference retired services or the Mango forwarding hook.
    patcher=ROOT/'tr3600/zt-firewall-defaults.py'
    replace(patcher,"out += ['uci -q commit firewall',tail.rstrip('\\n')]",
        """out += ['uci -q delete firewall.mango_proxy', 'uci -q delete firewall.mango_mark',
            'uci -q commit firewall', 'exit 0']""")
    replace(patcher,'for name in SECTIONS:\n        assert', "for name in SECTIONS:\n        if name in ('mango_proxy','mango_mark'): continue\n        assert")
    zone_spec=importlib.util.spec_from_file_location('ssrplus_zt_defaults',patcher)
    zone=importlib.util.module_from_spec(zone_spec);zone_spec.loader.exec_module(zone)
    (ss/'root/etc/uci-defaults/94-cudy-zt-zone').write_text(zone.patch(source),encoding='utf-8',newline='\n')
    files=ROOT/'files'
    # Keep owner DDNS configuration, not program files from an older image.
    # The package's first-boot hook recognizes and upgrades the known old
    # keep-settings resolver overlay without replacing custom owner code.
    (files/'lib/upgrade/keep.d/cudy-dynu-ddns').write_text('/etc/config/ddns\n',
        encoding='utf-8',newline='\n')
    for path in files.rglob('*'):
        if path.is_file() and path.name.startswith('mango-') and path.parent.name=='etc':
            path.unlink()
    (files/'etc/cudy-release').write_text('tr3600-ssrplus-1.2.0-test3\n')
    shutil.copy2(PROFILE/'migration.sh',files/'etc/uci-defaults/90-cudy-ssrplus-migrate')
    # Keep the same LED state machine, replace its proxy-specific adapter.
    led=ROOT/'tr3600/luci-app-cudy-led/root/usr/lib/lua/cudy/led-runtime.lua'
    s=led.read_text(encoding='utf-8')
    a=s.index('function M.identity()');b=s.index('function M.begin()',a)
    s=s[:a]+(PROFILE/'led-adapter.lua').read_text(encoding='utf-8')+s[b:]
    a=s.index("    local report=M.capture('/usr/libexec/mango-connectivity-probe")
    b=s.index('    local after=M.snapshot()',a)
    s=s[:a]+"""    local target=direct and 'https://www.baidu.com/' or 'https://www.google.com/generate_204'
    local report=M.capture('/usr/libexec/cudy-connectivity-probe '..before.mode.." && printf '\\\\nCUDY_PROBE_OK'")
    local ok=report:match('\\nCUDY_PROBE_OK$')~=nil
"""+s[b:]
    led.write_text(s,encoding='utf-8',newline='\n')
    probe=(ROOT/'tr3600/led-probe/mango-connectivity-probe').read_text(encoding='utf-8')
    probe=probe.replace(' --proxy socks5h://127.0.0.1:10809','')
    probe=probe.replace('/tmp/mango-connectivity-error.','/tmp/cudy-connectivity-error.')
    (ROOT/'tr3600/luci-app-cudy-led/root/usr/libexec/cudy-connectivity-probe').write_text(probe,encoding='utf-8',newline='\n')
    # Retain upgrade LED suspend/resume separately from the retired Mango probe.
    replace(p,'python3 "$kit/tr3600/upgrade-integration.py" "$PWD"',
        'python3 "$kit/tr3600/upgrade-integration.py" "$PWD"\npython3 "$kit/tr3600/ssrplus/upgrade-led.py" "$PWD"')
    (ROOT/'reports/ssrplus-source.json').write_text(json.dumps({
        'base':'tr3600-v1.1.1','ssrplus_commit':SSR_COMMIT,'mango_installed':False,
        'xray_version':'26.10.21','xray_source_tag':'v26.10.21',
        'xray_source_sha256':'44ef4874529a03848c90f1fdcfb763350fbc5f1de741ec90e0024d651df25650',
        'golang_feed_commit':'2a5d2301904f84ff61615dd4e4d1db6d4f1fbf67',
        'private_ss':'SSR Plus+ server_config row; isolated Xray namespace; same client policy',
        'ss_server_config_revision':3,
        'ddns_direct':'Dynu HTTPS curl sockets marked 255; WAN binding and TLS retained',
        'private_ss_ipv6':False,
        'hardware_validation':'pending'},indent=2)+'\n')
    print('Prepared SSR Plus+ build; no router was modified.')

if __name__=='__main__':prepare()

