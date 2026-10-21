-- Execute the real first-boot runner against private UCI and filesystem fixtures.
local recipe=arg[1]
local M=dofile(recipe..'/migration.lua')
local original={open=io.open,rename=os.rename,exit=os.exit,dofile=dofile}
local files,configs,fail_once,events
local fakeuci={}
function fakeuci:get_all(c,s) return configs[c] and configs[c][s] end
function fakeuci:get(c,s,k)
 local item=self:get_all(c,s);if not item then return nil end
 return k and item[k] or item['.type']
end
function fakeuci:foreach(c,t,fn)
 for _,s in ipairs((configs[c] or {})._order or {}) do
  local item=configs[c][s]
  if not t or item['.type']==t then fn(item) end
 end
end
function fakeuci:section(c,t,s,o)
 configs[c]=configs[c] or {_order={}}
 local item={['.name']=s,['.type']=t}
 for k,v in pairs(o or {}) do item[k]=v end
 configs[c][s]=item;table.insert(configs[c]._order,s);return s
end
function fakeuci:delete(c,s) configs[c][s]=nil;return true end
function fakeuci:set(c,s,k,v) configs[c][s][k]=v;return true end
function fakeuci:commit(c)
 if fail_once=='commit' then fail_once=nil;return false end
 files['/etc/config/'..c]='committed '..c
 return true
end
function fakeuci:revert() return true end
package.preload.uci=function()return {cursor=function()return fakeuci end}end
package.preload['nixio.fs']=function()return {
 mkdirr=function()return true end,chmod=function()return true end,
 unlink=function(p)files[p]=nil;return true end
}end
io.open=function(path,mode)
 if mode=='rb' then
  if not files[path] then return nil end
  return {read=function()return files[path]end,close=function()return true end}
 end
 assert(mode=='wb')
 if fail_once==path then fail_once=nil;return nil end
 files[path]=''
 return {write=function(self,text)files[path]=files[path]..text;return true end,
 close=function()return true end}
end
os.rename=function(a,b)assert(files[a]);files[b]=files[a];files[a]=nil;return true end
os.exit=function(code)error({exit_code=code})end
dofile=function(path)
 if path=='/usr/lib/mango/ssr-migration.lua' then return M end
 return original.dofile(path)
end
local function setup()
 files={['/etc/config/mango_proxy']='original legacy credentials',
 ['/etc/config/firewall']='original owner firewall', ['/etc/config/dhcp']='original owner DNS',
 ['/etc/config/shadowsocksr']='native defaults', ['/etc/ssrplus/white.list']='existing.example\n'}
 configs={mango_proxy={_order={'main','node1'},
 main={['.name']='main',['.type']='policy',mode='split',node='node1',direct_domains={'direct.example'}},
 node1={['.name']='node1',['.type']='node',protocol='shadowsocks',
 address='example.invalid',port='443',method='aes-128-gcm',password='fixture-only'}},
 firewall={_order={'mango_proxy','mango_zt_direct'},
 mango_proxy={['.name']='mango_proxy',['.type']='include',path='/usr/libexec/mango-fw'},
 mango_zt_direct={['.name']='mango_zt_direct',['.type']='include',path='/usr/libexec/mango-zt-direct',enabled='0'}},
 dhcp={_order={'dns'},dns={['.name']='dns',['.type']='dnsmasq',
 server={'127.0.0.1#1053','192.0.2.53#5353'},noresolv='1'}},
 shadowsocksr={_order={}}}
 fail_once=nil
end
local function run()
 local ok,err=pcall(original.dofile,recipe..'/migrate-run.lua')
 if ok then return 0 end
 if type(err)=='table' and err.exit_code then return err.exit_code end
 error(err)
end
setup()
assert(run()==0)
assert(files['/etc/config/mango_proxy']=='original legacy credentials')
assert(files['/etc/ssrplus/mango-migration/mango_proxy.original']=='original legacy credentials')
assert(files['/etc/ssrplus/mango-migration/completed'])
assert(not configs.firewall.mango_proxy)
assert(configs.firewall.mango_zt_direct.enabled=='0')
assert(configs.firewall.mango_zt_direct.path=='/usr/libexec/mango-zt-direct')
assert(configs.dhcp.dns.server[1]=='192.0.2.53#5353' and #configs.dhcp.dns.server==1)
assert(files['/etc/ssrplus/white.list']=='existing.example\ndirect.example\n')
local completed=files['/etc/config/shadowsocksr']
assert(run()==0 and files['/etc/config/shadowsocksr']==completed)
for _,failure in ipairs({'/etc/ssrplus/white.list.mango-new','commit'}) do
 setup()
 local snapshot={};for k,v in pairs(files)do snapshot[k]=v end
 fail_once=failure
 assert(run()==1)
 for k,v in pairs(snapshot)do assert(files[k]==v,k..' not restored')end
 assert(not files['/etc/ssrplus/mango-migration/completed'])
end
setup()
fakeuci:section('shadowsocksr','servers','native',{server='native.invalid'})
assert(run()==0 and files['/etc/config/shadowsocksr']=='native defaults')
setup();configs.mango_proxy.main=nil
assert(run()==0 and files['/etc/config/shadowsocksr']=='native defaults')
io.open,os.rename,os.exit,dofile=original.open,original.rename,original.exit,original.dofile
print('migration runner: original retention, native precedence, idempotence, owned include cleanup, custom DNS and rollback passed')
