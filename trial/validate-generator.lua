-- Run the actual pinned SSR Plus+ generator, then validate its JSON with real MIPS Xray.
local root,recipe,output=arg[1],arg[2],arg[3]
package.path=root..'/usr/lib/lua/?.lua;'..root..'/usr/lib/lua/?/init.lua;'..package.path
package.cpath=root..'/usr/lib/lua/?.so;'..package.cpath
local json=require('luci.jsonc')
-- Load real runtime dependencies before the command/UCI fixtures; a stub must not hide a missing package.
assert(require('luci.sys'))
assert(require('luci.model.uci'))
local datatypes=require('luci.cbi.datatypes')
assert(type(datatypes.hostname)=='function')
local M=dofile(recipe..'/migration.lua')
local quoted_path=assert(io.open(output..'/quoting','w'))
assert(quoted_path:write(M.encode({{type='test',name='owner',options={value="a' b $"..string.char(34,96)}}})))
assert(quoted_path:close())
-- Round-trip the migration's quoting through the actual target libuci parser.
local real_uci=require('uci').cursor(output,output)
assert(real_uci:load('quoting'))
assert(real_uci:get('quoting','owner','value')=="a' b $"..string.char(34,96))
local output_json
luci={sys={exec=function(cmd)
 if cmd:find('xray version',1,true) then return 'Xray 26.3.27\n' end
 if cmd:find('xray',1,true) then return '/usr/bin/xray\n' end
 return ''
end}}
nixio={bin={b64decode=function()error('Unexpected Base64 path')end,b64encode=function()error('Unexpected Base64 path')end}}
package.loaded['luci.sys']=luci.sys
package.loaded['luci.cbi.datatypes']=datatypes
package.loaded['luci.jsonc']={parse=json.parse,stringify=function(o) output_json=o;return json.stringify(o)end}
local current,socks
package.loaded['luci.model.uci']={cursor=function()return {
 get_all=function(self,config,section)
  if section=='fixture' then return current end
  if section=='@socks5_proxy[0]' then return socks end
  if section=='@global_xray_fragment[0]' then return {fragment='0',noise='0'} end
  if section=='@xray_noise_packets[0]' then return {enabled='0'} end
  return {}
 end,
 get_first=function(self,config,section,option,default)return default end,
 get=function()return nil end
}end}
local cases={
 {name='vless-reality-vision',protocol='vless',address='v.example.com',port='443',
  uuid='11111111-1111-4111-8111-111111111111',sni='s.example.com',
  public_key=string.rep('a',43),short_id='ab12',fingerprint='chrome'},
 {name='vmess-raw',protocol='vmess',address='m.example.com',port='443',
  uuid='22222222-2222-4222-8222-222222222222',network='raw',tls='none'},
 {name='vmess-ws-tls',protocol='vmess',address='m.example.com',port='443',
  uuid='22222222-2222-4222-8222-222222222222',network='ws',tls='tls',
  sni='m.example.com',ws_path='/websocket',ws_host='cdn.example.com'},
}
for _,cipher in ipairs({'aes-128-gcm','aes-256-gcm','chacha20-ietf-poly1305'}) do
 cases[#cases+1]={name='ss-'..cipher,protocol='shadowsocks',address='s.example.com',
 port='443',method=cipher,password='fixture-only'}
end
local original_print=print
for _,node in ipairs(cases)do
 node['.name']='fixture'
 current=M.node(node);socks={socks5_auth='noauth',server='same',mango_expose='0'}
 arg={'fixture','tcp,udp','12345','10808'}
 print=function(text)
  local file=assert(io.open(output..'/'..node.name..'.json','w'));file:write(text);file:close()
 end
 dofile(root..'/usr/share/shadowsocksr/gen_config.lua')
 assert(output_json.outbounds[1].protocol==node.protocol)
 local found=false
 for _,inbound in ipairs(output_json.inbounds)do
  if inbound.protocol=='socks' then found=true;assert(inbound.listen=='127.0.0.1')end
 end
 assert(found,'Missing shared SOCKS inbound')
 if node.protocol=='vless' then
  assert(output_json.outbounds[1].settings.vnext[1].users[1].flow=='xtls-rprx-vision')
 end
 if node.tls=='tls' then assert(output_json.outbounds[1].streamSettings.tlsSettings.allowInsecure==false)end
end
print=original_print
print('Actual SSR generator: six migrated VLESS/VMess/SS configurations generated')
