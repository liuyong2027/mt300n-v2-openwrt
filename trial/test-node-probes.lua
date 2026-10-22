-- Exercise the actual controller with isolated network/HTTP dependencies.
if arg[2] and arg[2]~='' then
 package.path=arg[2]..'/usr/lib/lua/?.lua;'..arg[2]..'/usr/lib/lua/?/init.lua;'..package.path
 package.cpath=arg[2]..'/usr/lib/lua/?.so;'..package.cpath
end
require('luci.sys')
require('luci.http')
require('luci.cbi.datatypes')
local nixio=require('nixio')
local values,calls,reply,backend,present
nixio.socket=function()
 return {setopt=function()return true end,connect=function()return true end,close=function()end}
end
luci.http.formvalue=function(k)return values[k]end
luci.http.prepare_content=function()end
luci.http.write_json=function(e)reply=e end
luci.sys.exec=function()return '1' end
luci.sys.call=function(command)
 calls[#calls+1]=command
 if command=='command -v nft >/dev/null' then return backend=='nft' and 0 or 1 end
 if command:find('nft get element',1,true) or command:find('ipset test',1,true) then return present and 0 or 1 end
 return 0
end
dofile(assert(arg[1],'Controller path required'))
local controller=assert(package.loaded['luci.controller.shadowsocksr'])
local cases={
 {'node.example','nft',false,0,0},
 {'192.0.2.10','nft',true,0,0},
 {'192.0.2.10','nft',false,1,1},
 {'192.0.2.10','ipset',true,0,0},
 {'192.0.2.10','ipset',false,1,1},
 {'999.999.999.999','nft',false,0,0},
}
for index,c in ipairs(cases) do
 values={domain=c[1],port='443',index=tostring(index)}
 backend=c[2];present=c[3];calls={};reply=nil
 controller.act_ping()
 assert(reply and reply.socket==true and reply.ping==1,'Probe response changed')
 local adds,deletes=0,0
 for _,cmd in ipairs(calls) do
  if cmd:find('nft add element',1,true) or cmd:find('ipset add',1,true) then adds=adds+1 end
  if cmd:find('nft delete element',1,true) or cmd:find('ipset del',1,true) then deletes=deletes+1 end
 end
 assert(adds==c[4] and deletes==c[5],'Probe changed a domain or existing bypass: case '..index)
end
print('NODE_PROBE_FIREWALL_REGRESSION_CASES=6; STATUS=passed')
