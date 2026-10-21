local M=dofile(arg[1]..'/migration.lua')
local function eq(a,b) assert(a==b,tostring(a)..' ~= '..tostring(b)) end
local nodes={
 {['.name']='primary',protocol='vless',address='v.example.com',port='443',label="owner's primary",uuid='11111111-1111-4111-8111-111111111111',sni='s.example.com',public_key=string.rep('a',43),short_id='ab12'},
 {['.name']='backup',protocol='vmess',address='m.example.com',port='8443',uuid='22222222-2222-4222-8222-222222222222',network='ws',tls='tls',sni='m.example.com',ws_path='/path',ws_host='cdn.example.com'},
 {['.name']='ss',protocol='shadowsocks',address='s.example.com',port='443',method='aes-128-gcm',password="x' $"..string.char(34,96)},
}
local p={mode='split',node='primary',backup_nodes={'ss','backup'},failover='1',
 direct_domains={'example.cn'},bypass4={'18.1.2.0/24'},socks_server='1',socks_port='10810',subscription_url='https://example.invalid/sub'}
local r=M.plan(p,nodes)
eq(r.sections[1].options.global_server,'primary')
eq(r.sections[1].options.run_mode,'router')
eq(r.sections[1].options.enable_switch,'1')
eq(r.sections[4].options.local_port,'10810')
eq(r.sections[4].options.mango_expose,'1')
eq(r.sections[7].name,'primary')
eq(r.sections[8].name,'ss')
eq(r.sections[9].name,'backup')
eq(r.sections[7].options.tls_flow,'xtls-rprx-vision')
eq(r.sections[9].options.transport,'ws')
eq(r.sections[8].options.password,nodes[3].password)
eq(r.sections[3].options.Interface[2],'zt+')
eq(r.sections[3].options.wan_bp_ips[1],'18.1.2.0/24')
assert(M.encode(r.sections):find("owner'\\''s primary",1,true))
for mode,target in pairs({direct='router',global='all',gfw='gfw'}) do
 p.mode=mode
 local x=M.plan(p,nodes)
 eq(x.sections[1].options.run_mode,target)
 eq(x.sections[1].options.global_server,mode=='direct' and 'nil' or 'primary')
 eq(x.sections[1].options.mango_direct_socks,mode=='direct' and '1' or '0')
end
p.mode='split';p.backup_nodes={'missing'}
assert(not pcall(M.plan,p,nodes))
p.backup_nodes={};p.node='missing';assert(not pcall(M.plan,p,nodes))
assert(not pcall(M.encode,{{type='servers',name='a',options={password='x\ny'}}}))
print('migration: protocols, REALITY, WS/TLS, SS credentials, backup order, modes, whitelist, subscription, SOCKS and rejected invalid input passed')
