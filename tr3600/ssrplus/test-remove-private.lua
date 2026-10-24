-- Use actual packed ARM64 libuci with synthetic files only.
local module,root=arg[1],arg[2]
assert(root:match('^/tmp/[%w_./-]+$') and not root:find('..',1,true))
local fs=require('nixio.fs');local native=require('uci')
assert(not fs.access(root));assert(fs.mkdir(root))
local cleanup=dofile(module)
local function same(a,b)
 if type(a)~=type(b) then return false end
 if type(a)~='table' then return a==b end
 for k,v in pairs(a) do if not same(v,b[k]) then return false end end
 for k in pairs(b) do if a[k]==nil then return false end end
 return true
end
for _,case in ipairs({'enabled','disabled','legacy_only','fresh','collision'}) do
 local dir=root..'/'..case;assert(fs.mkdir(dir));assert(fs.mkdir(dir..'/saved'))
 local u=native.cursor(dir,dir..'/saved')
 local function section(pkg,kind,id,values)
  assert(u:set(pkg,id,kind));for k,v in pairs(values or {}) do assert(u:set(pkg,id,k,v)) end
 end
 -- Files must exist for native libuci packages that contain no owner rows.
 for _,pkg in ipairs({'shadowsocksr','network','firewall'}) do assert(fs.writefile(dir..'/'..pkg,'')) end
 section('shadowsocksr','server_global','sg',{enable_server=case=='enabled' and '1' or '0'})
 section('shadowsocksr','global','global',{global_server='owner_node',run_mode='gfw'})
 section('shadowsocksr','servers','owner_node',{server='owner.example',password='ordinary-node-key'})
 section('shadowsocksr','server_config','ordinary',{type='shadowsocks',enable='1',server_port='18388',
  ss_method='aes-256-gcm',ss_password='ordinary-server-key',ss_network='tcp,udp',cudy_access='public'})
 section('network','interface','lan',{ipaddr='192.168.9.1',device='br-lan'})
 section('firewall','zone','lan',{name='lan'});section('firewall','zone','wan',{name='wan'})
 section('firewall','zone','mango_zt',{name='mangozt'})
 section('firewall','rule','zerotier_direct',{name='ZeroTier direct UDP',dest_port='9993 20089 48170'})
 section('firewall','rule','zerotier_ssdp',{name='ZeroTier UPnP discovery',src_ip='192.168.0.1',src_port='1900'})
 section('firewall','include','owner',{path='/etc/owner-hook'})
 if case~='fresh' and case~='legacy_only' then
  section('shadowsocksr','server_config','cudy_zt_private',{type='shadowsocks',enable=case=='enabled' and '1' or '0',
   cudy_private='1',cudy_access='zerotier',ss_password='retired-private-key',server_port='8388'})
 end
 if case~='fresh' then
  section('firewall','zone','cudy_ss',{name='cudyss'})
  section('firewall','include','cudy_ss_guard',{path='/etc/cudy-ss/guard.nft'})
  for _,id in ipairs({'cudy_ss_to_wan','cudy_ss_to_lan','cudy_ss_to_zt','cudy_zt_to_ss','cudy_ss_route_guard','cudy_zt_ipv6_guard'}) do
   section('firewall','rule',id,{src='synthetic-old-private'})
  end
 end
 if case=='collision' then section('firewall','zone','ssr_ss',{name='owner-zone'}) end
 for _,pkg in ipairs({'shadowsocksr','network','firewall'}) do assert(u:commit(pkg)) end
 local before={};for _,pkg in ipairs({'shadowsocksr','network','firewall'}) do before[pkg]=u:get_all(pkg) end
 local files={};for _,p in ipairs({'/etc/config/cudy_ss','/etc/cudy-ss/guard.nft',
  '/etc/cudy-ssrplus/cudy_ss.before-migration','/etc/cudy-ssrplus/cudy_ss.before-server-v2','/etc/cudy-ssrplus/ss-server-v2.done'}) do files[p]=true end
 local removed={};local fakefs={access=function(p)return files[p] end,remove=function(p)files[p]=nil;removed[p]=true;return true end}
 local ok,error=pcall(cleanup.run,u,fakefs)
 if case=='collision' then
  assert(not ok);for pkg,s in pairs(before) do assert(same(s,u:get_all(pkg))) end
  assert(not next(removed));print('PASS collision: unrelated owner resource unchanged')
 else
  assert(ok,error)
  assert(not u:get('shadowsocksr','cudy_zt_private'));assert(not next(files))
  for _,id in ipairs({'ordinary','owner_node','global','sg'}) do assert(same(before.shadowsocksr[id],u:get_all('shadowsocksr',id))) end
  for _,id in ipairs({'zerotier_direct','zerotier_ssdp','owner','mango_zt','lan','wan'}) do
   assert(same(before.firewall[id],u:get_all('firewall',id)))
  end
  assert(same(before.network.lan,u:get_all('network','lan')))
  for id in pairs(before.firewall) do if id:match('^cudy_') then assert(not u:get('firewall',id)) end end
  assert(u:get('firewall','ssr_ss','name')=='ssrservers')
  assert(u:get('firewall','ssr_ss_to_wan','src')=='ssrservers')
  local once={};for _,pkg in ipairs({'shadowsocksr','network','firewall'}) do once[pkg]=u:get_all(pkg) end
  cleanup.run(u,fakefs)
  for pkg,s in pairs(once) do assert(same(s,u:get_all(pkg))) end
  print('PASS '..case..': private deleted; ordinary SS, client, ZeroTier rules preserved; repeat no-op')
 end
end
print('PASS all 5 native private SS deletion cases')
