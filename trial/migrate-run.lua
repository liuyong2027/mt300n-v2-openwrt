#!/usr/bin/lua
-- Configuration-only first-boot migration; never connects to a proxy or ZeroTier.
local uci=require('uci').cursor()
local fs=require('nixio.fs')
local M=dofile('/usr/lib/mango/ssr-migration.lua')
local function read(path)
    local f=io.open(path,'rb'); if not f then return nil end
    local s=f:read('*a'); f:close(); return s
end
local function write(path,data)
    local f=assert(io.open(path,'wb'));assert(f:write(data));assert(f:close())
end
local function section_snapshot(config)
    local out={}
    uci:foreach(config,nil,function(s)
        local options={};for k,v in pairs(s) do if k:sub(1,1)~='.' then options[k]=v end end
        out[#out+1]={type=s['.type'],name=s['.name'],options=options}
    end)
    return out
end
local marker='/etc/ssrplus/mango-migration/completed'
if read(marker) then os.exit(0) end
-- Native SSR Plus+ user settings have priority over an automatic legacy migration.
local has_native=false
uci:foreach('shadowsocksr','servers',function() has_native=true end)
if has_native then os.exit(0) end
local old=read('/etc/config/mango_proxy')
local p=uci:get_all('mango_proxy','main')
if not p then
    -- Fresh installations remain disabled; no legacy state to convert.
    os.exit(0)
end
local nodes={}
uci:foreach('mango_proxy','node',function(s) nodes[#nodes+1]=s end)
local result=M.plan(p,nodes) -- Validate all node fields before changing any file.
local root='/etc/ssrplus/mango-migration'
assert(fs.mkdirr(root))
assert(fs.chmod(root,'rwx------')) -- nixio accepts symbolic or octal-text modes, not POSIX bit integers.
local before={}
local targets={
    '/etc/config/shadowsocksr','/etc/config/firewall','/etc/config/dhcp',
    '/etc/ssrplus/white.list','/etc/ssrplus/black.list','/etc/ssrplus/gfw_list.conf',
    '/etc/ssrplus/china_ssr.txt'
}
for i,path in ipairs(targets) do
    before[path]=read(path)
    if before[path] then
        if read('/rom'..path)==before[path] then
            -- Immutable defaults remain recoverable from SquashFS; do not copy large rule lists to overlay.
            write(root..'/original-'..i..'.rom','/rom'..path..'\n')
        else
            write(root..'/original-'..i,before[path])
        end
    end
end
write(root..'/mango_proxy.original',assert(old))
local function stage(path,text)
    write(path..'.mango-new',text)
    assert(fs.chmod(path..'.mango-new','rw-------'))
    assert(os.rename(path..'.mango-new',path))
end
local ok,err=pcall(function()
    stage('/etc/config/shadowsocksr',M.encode(result.sections))
    local white={}
    for line in (before['/etc/ssrplus/white.list'] or ''):gmatch('[^\r\n]+') do white[#white+1]=line end
    for _,domain in ipairs(result.white) do white[#white+1]=domain end
    local gfw=read('/etc/mango-rules/gfw-domains.txt')
    if gfw then
        local proxy={}
        for line in gfw:gmatch('[^\r\n]+') do
            local flag,domain=line:match('^([+-])([a-z0-9%.%-]+)$')
            assert(flag,'Unrecognized custom GFW rule')
            if flag=='-' then white[#white+1]=domain
            else
                proxy[#proxy+1]='server=/'..domain..'/127.0.0.1#5335'
                proxy[#proxy+1]='nftset=/'..domain..'/4#inet#ss_spec#gfwlist'
                proxy[#proxy+1]='nftset=/'..domain..'/4#ip#ss_spec_mangle#gfwlist'
            end
        end
        stage('/etc/ssrplus/gfw_list.conf',table.concat(proxy,'\n')..'\n')
    end
    stage('/etc/ssrplus/white.list',table.concat(white,'\n')..'\n')
    local cn=read('/etc/mango-rules/cn-cidrs.txt')
    if cn then
        for line in cn:gmatch('[^\r\n]+') do
            assert(line:match('^%d+%.%d+%.%d+%.%d+/%d+$'),'Invalid custom CIDR')
        end
        stage('/etc/ssrplus/china_ssr.txt',cn)
    end
    -- Remove only the retired include that explicitly names Mango's proxy helper.
    if uci:get('firewall','mango_proxy')=='include' and
       uci:get('firewall','mango_proxy','path')=='/usr/libexec/mango-fw' then
        assert(uci:delete('firewall','mango_proxy'))
    end
    -- Preserve every ZeroTier zone, forwarding, local.conf and identity byte.
    if not uci:get('firewall','shadowsocksr') then
        assert(uci:set('firewall','shadowsocksr','include'))
        for key,value in pairs({type='script',path='/var/etc/shadowsocksr.include',fw4_compatible='1'}) do
            assert(uci:set('firewall','shadowsocksr',key,value))
        end
    end
    -- Retire only DNS values emitted by the old proxy. Keep custom DNS entries.
    uci:foreach('dhcp','dnsmasq',function(s)
        local servers=s.server
        if type(servers)=='string' then servers={servers} end
        local kept,changed={},false
        for _,value in ipairs(servers or {}) do
            if value=='127.0.0.1#1053' then changed=true else kept[#kept+1]=value end
        end
        if changed then
            if #kept==0 then kept={'223.5.5.5','119.29.29.29'} end
            assert(uci:set('dhcp',s['.name'],'server',kept))
        end
    end)
    assert(uci:commit('firewall'));assert(uci:commit('dhcp'))
    assert(read('/etc/config/mango_proxy')==old,'Legacy configuration unexpectedly changed')
    stage(marker,'23-ssrplus: '..result.node_count..' legacy nodes migrated; hardware acceptance pending\n')
end)
if not ok then
    uci:revert('firewall');uci:revert('dhcp')
    for _,path in ipairs(targets) do
        if read(path)~=before[path] then
            if before[path] then stage(path,before[path]) else fs.unlink(path) end
        end
    end
    fs.unlink(marker)
    local where=tostring(err):match(':%d+:') or ''
    io.stderr:write('SSR Plus+ migration failed '..where..'; original files restored\n')
    os.exit(1) -- Do not log credentials or arbitrary config contents.
end
print('Legacy configuration migration completed; original Mango configuration retained')
