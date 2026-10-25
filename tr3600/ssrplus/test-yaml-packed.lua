-- Run against unpacked image programs. No real UCI cursor is created.
local root,sandbox,fixture,version=assert(arg[1]),assert(arg[2]),assert(arg[3]),assert(arg[4])
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
local seen={}
for _,node in ipairs(nodes)do
 selected=node;arg={'yaml_node','tcpudp','34567','0','0'}
 local original_print=print;local output={};print=function(value)output[#output+1]=tostring(value)end
 local ok=pcall(function()assert(loadfile(root..'/usr/share/shadowsocksr/gen_config.lua'))()end)
 print=original_print
 assert(ok,'Installed generator rejected synthetic YAML node')
 local body=table.concat(output,'\n');local doc=assert(json.parse(body))
 assert(doc.outbounds and doc.outbounds[1],'Missing generated outbound')
 assert(fs.writefile(sandbox..'/'..node.v2ray_protocol..'.json',body))
 seen[node.v2ray_protocol]=true
end
assert(seen.anytls and seen.vmess and seen.hysteria2)
print('PASS packed lyaml and installed generator: AnyTLS, VMess, Hysteria2; no production UCI access')
