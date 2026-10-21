-- Real io.popen and shell lookup with no external timeout binary in PATH.
local root,fixture=arg[1],arg[2]
assert(root and fixture)
package.path=root..'/package/luci-app-mango-proxy/root/usr/lib/?.lua;'..package.path
local original_open=io.open
local config={['zerotier.global.enabled']='1',
 ['zerotier.global.local_conf_path']='/fixture/local.conf',
 ['firewall.mango_zt_direct']='include',
 ['firewall.mango_zt_direct.path']='/usr/libexec/mango-zt-direct'}
package.preload['uci']=function() return {cursor=function() return {get=function(self,c,s,o)
 return config[c..'.'..s..(o and '.'..o or '')]
end} end} end
io.open=function(path,mode)
 if path=='/tmp/sysinfo/board_name' then path=fixture..'/board'
 elseif path=='/fixture/local.conf' then path=fixture..'/local.conf' end
 return original_open(path,mode)
end
arg={}
assert(loadfile(root..'/package/luci-app-mango-proxy/root/usr/libexec/mango-zt-direct-run'))()
