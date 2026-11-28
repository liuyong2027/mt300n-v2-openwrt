-- Run against unpacked image programs. No real UCI cursor is created.
local root,sandbox,fixture,version=assert(arg[1]),assert(arg[2]),assert(arg[3]),assert(arg[4])
local test_buffers=arg[5]=='hy2-buffers'
local fs=require('nixio.fs');local json=require('luci.jsonc')
assert(sandbox:match('^/tmp/') and not sandbox:find('..',1,true),'Unsafe test directory')
assert(not fs.lstat(sandbox),'Test directory already exists')
assert(fs.mkdir(sandbox) and fs.chmod(sandbox,'700'))
local helper=dofile(root..'/usr/share/shadowsocksr/yaml_nodes.lua')
local nodes=helper.parse(assert(fs.readfile(fixture)))
assert(#nodes==3,'Mixed YAML fixture must contain three nodes')
local selected;local fake={}
function fake:get_all(config,section)
 assert(config=='shadowsocksr')
 if section=='yaml_node'then return selected end
 return{}
end
function fake:get_first(config,kind,option,default)assert(config=='shadowsocksr');return default end
function fake:get(config,section,option)return self:get_all(config,section)[option]end
local lu=require('luci.model.uci');lu.cursor=function()return fake end
local sys=require('luci.sys')
sys.exec=function(command)
 if command:match('^type %-t %-p ')then
  return command:find('"xray"',1,true)and(root..'/usr/bin/xray\n')or''
 end
 if command=='xray version 2>&1'then return version end
 error('Unexpected external generator command')
end
sys.call=function()error('External mutation is forbidden in YAML packed tests')end
local function generate(node)
 selected=node;arg={'yaml_node','tcpudp','34567','0','0'}
 local original_print=print;local output={};print=function(value)output[#output+1]=tostring(value)end
 local ok=pcall(function()assert(loadfile(root..'/usr/share/shadowsocksr/gen_config.lua'))()end)
 print=original_print
 assert(ok,'Installed generator rejected synthetic YAML node')
 local body=table.concat(output,'\n');local doc=assert(json.parse(body))
 local outbound=assert(doc.outbounds and doc.outbounds[1],'Missing generated outbound')
 return body,assert(outbound.streamSettings.sockopt)
end
local seen={}
for _,node in ipairs(nodes)do
 local body,sockopt=generate(node)
 assert(sockopt.mark==255 and sockopt.customSockopt==nil,'Unexpected default socket options')
 assert(fs.writefile(sandbox..'/'..node.v2ray_protocol..'.json',body))
 seen[node.v2ray_protocol]=node
end
assert(seen.anytls and seen.vmess and seen.hysteria2)
print('PASS packed lyaml and installed generator: AnyTLS, VMess, Hysteria2; no production UCI access')
if test_buffers then
 local hy2=seen.hysteria2
 hy2.hy2_udp_rcvbuf_mib='4'
 hy2.hy2_udp_sndbuf_mib='2'
 local body,sockopt=generate(hy2)
 local custom=sockopt.customSockopt
 assert(sockopt.mark==255 and #custom==2,'Expected both buffers and the routing mark')
 assert(custom[1].opt=='8' and custom[1].value=='4194304','Wrong receive buffer request')
 assert(custom[2].opt=='7' and custom[2].value=='2097152','Wrong send buffer request')
 for _,option in ipairs(custom)do
  assert(option.system=='linux' and option.network=='udp' and option.level=='1' and option.type=='int')
 end
 assert(fs.writefile(sandbox..'/hysteria2-buffers.json',body))
 hy2.hy2_udp_rcvbuf_mib='1.5'
 local _,one_buffer=generate(hy2)
 assert(#one_buffer.customSockopt==1 and one_buffer.customSockopt[1].opt=='7','Invalid receive sizes must be ignored')
 hy2.hy2_udp_sndbuf_mib='17'
 local _,invalid=generate(hy2)
 assert(invalid.customSockopt==nil,'Invalid buffer sizes must be ignored')
 local vmess=seen.vmess
 vmess.hy2_udp_rcvbuf_mib='4'
 local _,other_protocol=generate(vmess)
 assert(other_protocol.customSockopt==nil,'UDP buffer settings are specific to the selected Hysteria2 node')
 print('PASS optional per-node Hysteria2 UDP receive and send buffer requests')
end
