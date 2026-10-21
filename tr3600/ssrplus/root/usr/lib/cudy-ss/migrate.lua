local fs=require('nixio.fs')
local u=require('uci').cursor()
if fs.access('/etc/cudy-ssrplus/migration-v1.done') then return end
local g=u:get_first('shadowsocksr','global')
if not g then g=u:section('shadowsocksr','global','global',{}) end
local mode=u:get('mango_proxy','main','mode') or 'direct'
local mapped={}
local fields={
    address='server',port='server_port',uuid='vmess_id',sni='tls_host',
    public_key='reality_publickey',short_id='reality_shortid',fingerprint='fingerprint',
    spider_x='reality_spiderx',method='encrypt_method_ss',password='password',
    ws_host='ws_host',ws_path='ws_path',vmess_security='security',tls='tls'
}
u:foreach('mango_proxy','node',function(n)
    local id='migrated_'..n['.name']
    assert(id:match('^[%w_]+$'),'Invalid old node name')
    local existing=u:get('shadowsocksr',id)
    assert(not existing or (existing=='servers' and u:get('shadowsocksr',id,'cudy_migration_source')==n['.name']), 'Migration node name collision')
    local proto=n.protocol or 'vless'
    assert(proto=='vless' or proto=='shadowsocks' or proto=='vmess','Unsupported old node')
    if not existing then
        assert(u:section('shadowsocksr','servers',id,{type='v2ray',v2ray_protocol=proto,
            alias=n.label or n['.name'],local_port='1234',cudy_migration_source=n['.name']}))
    end
    for old,new in pairs(fields) do if n[old] then assert(u:set('shadowsocksr',id,new,n[old])) end end
    if proto=='vless' then
        u:set('shadowsocksr',id,'transport','raw')
        u:set('shadowsocksr',id,'reality','1')
        u:set('shadowsocksr',id,'tls','0')
        u:set('shadowsocksr',id,'tls_flow','xtls-rprx-vision')
    elseif proto=='vmess' then
        u:set('shadowsocksr',id,'transport',n.network or 'raw')
        u:set('shadowsocksr',id,'tls',n.tls=='tls' and '1' or '0')
        u:set('shadowsocksr',id,'alter_id','0')
    end
    mapped[n['.name']]=id
end)
local active=u:get('mango_proxy','main','node')
-- Existing SSR Plus+ settings take precedence when this profile is upgraded.
if fs.access('/etc/cudy-ssrplus/seeded-config') or not u:get('shadowsocksr',g,'global_server') then
    u:set('shadowsocksr',g,'global_server',mode=='direct' and 'nil' or (mapped[active] or 'nil'))
end
local runmode=({split='router',global='all',gfw='gfw',direct='router'})[mode]
assert(runmode,'Unknown old proxy mode')
u:set('shadowsocksr',g,'run_mode',runmode)
u:set('shadowsocksr',g,'udp_relay_server','same')
u:set('shadowsocksr',g,'prefer_nft','1')
u:set('shadowsocksr',g,'default_node_local_port','1234')
u:set('shadowsocksr',g,'dports','3')
u:set('shadowsocksr',g,'custom_ports','1-65535')
-- No unencrypted fallback when the active relay supports UDP.
u:set('shadowsocksr',g,'router_proxy','1')
local ac=u:get_first('shadowsocksr','access_control')
if not ac then ac=u:section('shadowsocksr','access_control','access_control',{}) end
local interfaces=u:get('shadowsocksr',ac,'Interface') or {'lan'}
if type(interfaces)=='string' then interfaces={interfaces} end
local interface_present=false
for _,v in ipairs(interfaces) do if v=='cudy_ss' then interface_present=true end end
if not interface_present then interfaces[#interfaces+1]='cudy_ss' end
u:set('shadowsocksr',ac,'Interface',interfaces)
u:set('shadowsocksr',ac,'router_proxy','1')
local bypass=u:get('shadowsocksr',ac,'wan_bp_ips') or {}
if type(bypass)=='string' then bypass={bypass} end
local present=false;for _,v in ipairs(bypass) do if v=='198.18.255.0/30' then present=true end end
if not present then bypass[#bypass+1]='198.18.255.0/30' end
local old_bypass=u:get('mango_proxy','main','bypass4') or {}
if type(old_bypass)=='string' then old_bypass={old_bypass} end
for _,v in ipairs(old_bypass) do bypass[#bypass+1]=v end
u:set('shadowsocksr',ac,'wan_bp_ips',bypass)
local dns
u:foreach('dhcp','dnsmasq',function(s) if not dns then dns=s['.name'] end end)
assert(dns,'Missing dnsmasq instance')
local servers=u:get('dhcp',dns,'server') or {}
if type(servers)=='string' then servers={servers} end
local retained={}
for _,v in ipairs(servers) do if v~='127.0.0.1#1053' then retained[#retained+1]=v end end
if #retained==0 then retained={'223.5.5.5','119.29.29.29'} end
u:set('dhcp',dns,'server',retained)
u:set('dhcp',dns,'filter_aaaa',mode=='direct' and '0' or '1')
-- Retire exactly the known Mango script include, never delete arbitrary hooks.
local include=u:get_all('firewall','mango_proxy')
if include then
    assert(include.path=='/usr/libexec/mango-fw','Unrecognized Mango firewall include')
    u:delete('firewall','mango_proxy')
end
u:delete('firewall','mango_mark')
for _,name in ipairs({'shadowsocksr','dhcp','firewall'}) do assert(u:commit(name)) end
assert(fs.writefile('/etc/cudy-ssrplus/migration-v1.done','1\n'))
assert(fs.chmod('/etc/cudy-ssrplus/migration-v1.done','600'))
fs.remove('/etc/cudy-ssrplus/seeded-config')

