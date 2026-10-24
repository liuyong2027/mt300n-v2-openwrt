-- Import connection parameters only. No rule, DNS, group, or listener changes.
local M = {}
local MAX_BYTES, MAX_NODES = 4194304, 5000
local function fail(code) error('yaml_nodes:' .. code, 0) end
local function str(v, required)
 if v == nil then if required then fail('missing_value') end; return nil end
 if type(v) ~= 'string' and type(v) ~= 'number' then fail('invalid_scalar') end
 v=tostring(v);if v:find('[%c]') or #v>8192 or (required and #v==0) then fail('invalid_scalar') end
 return v
end
local function integer(v, lo, hi)
 local n=tonumber(v);if not n or n~=math.floor(n) or n<lo or n>hi then fail('invalid_integer') end
 return tostring(n)
end
local function flag(v)
 if v==nil then return nil end
 if v==true or v=='true' or v==1 or v=='1' then return '1' end
 if v==false or v=='false' or v==0 or v=='0' then return '0' end
 fail('invalid_boolean')
end
local function known(t, keys)
 local set={};for k in keys:gmatch('%S+') do set[k]=true end
 for k in pairs(t) do if not set[k] then fail('unsupported_field:'..tostring(k):gsub('[^%w_-]','?'):sub(1,64)) end end
end
local function list(v)
 if v==nil then return nil end
 if type(v)~='table' then return str(v,true) end
 local out={};for _,s in ipairs(v) do out[#out+1]=str(s,true) end
 if #out==0 then fail('empty_list') end
 return table.concat(out,',')
end
local function tls(p,n,enabled)
 n.tls=enabled and '1' or '0';n.insecure=flag(p['skip-cert-verify']) or '0'
 n.tls_host=str(p.sni or p.servername);n.tls_alpn=list(p.alpn)
 n.fingerprint=str(p['client-fingerprint'])
 n.tls_CertByName=str(p['name-cert-verify'])
 if p.fingerprint and p.fingerprint~='' then
  local pin=str(p.fingerprint,true):gsub(':',''):lower()
  if #pin~=64 or pin:find('[^%x]') then fail('invalid_certificate_fingerprint') end
  n.tls_CertSha=pin
 end
end
local common='name type server port udp tfo sni servername skip-cert-verify alpn client-fingerprint name-cert-verify fingerprint'
function M.convert(p)
 if type(p)~='table' then fail('invalid_node') end
 local kind=str(p.type,true):lower();if kind=='hy2' then kind='hysteria2' end
 if kind~='anytls' and kind~='vmess' and kind~='hysteria2' then fail('unsupported_type:'..kind:gsub('[^%w_-]','?'):sub(1,32)) end
 local server=str(p.server,true):gsub('^%[',''):gsub('%]$','')
 if #server>253 or server:find('[^%w_.:%-]') then fail('invalid_server') end
 if p.udp~=nil and flag(p.udp)=='0' then fail('per_node_udp_disable_not_supported') end
 local n={type='v2ray',v2ray_protocol=kind,server=server,server_port=integer(p.port or 443,1,65535),transport='raw',mux='0',kcp_param='--nocomp'}
 n.alias=str(p.name) or (server..':'..n.server_port);n.raw_alias=n.alias
 n.fast_open=flag(p.tfo)
 if kind=='anytls' then
  known(p,common..' password idle-session-check-interval idle-session-timeout min-idle-session')
  n.password=str(p.password,true);tls(p,n,true)
  for _,v in ipairs({{'idle-session-check-interval','anytls_idle_session_check_interval'},{'idle-session-timeout','anytls_idle_session_timeout'},{'min-idle-session','anytls_min_idle_session'}}) do
   if p[v[1]]~=nil then n[v[2]]=integer(p[v[1]],0,86400) end
  end
 elseif kind=='vmess' then
  known(p,common..' uuid alterId cipher tls network ws-opts ws-path ws-headers grpc-opts h2-opts')
  n.vmess_id=str(p.uuid,true)
  if not n.vmess_id:match('^%x%x%x%x%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x$') then fail('invalid_uuid') end
  n.alter_id=integer(p.alterId or 0,0,65535);n.security=str(p.cipher) or 'auto'
  if not ({auto=1,none=1,zero=1,['aes-128-gcm']=1,['chacha20-poly1305']=1})[n.security] then fail('unsupported_vmess_cipher') end
  tls(p,n,flag(p.tls)=='1')
  local network=p.network or 'tcp'
  if network=='tcp' or network=='raw' then n.transport='raw'
  elseif network=='ws' then
   n.transport='ws';local opts=p['ws-opts'] or {};known(opts,'path headers')
   local legacy_headers=p['ws-headers'] or {};known(legacy_headers,'Host host User-Agent user-agent')
   local headers=opts.headers or legacy_headers;known(headers,'Host host User-Agent user-agent')
   if opts.path and p['ws-path'] and opts.path~=p['ws-path'] then fail('conflicting_ws_path') end
   local host=headers.Host or headers.host;local legacy_host=legacy_headers.Host or legacy_headers.host
   if host and legacy_host and host~=legacy_host then fail('conflicting_ws_host') end
   n.ws_path=str(opts.path or p['ws-path']) or '/';n.ws_host=str(host or legacy_host)
   local agent=headers['User-Agent'] or headers['user-agent'];local legacy_agent=legacy_headers['User-Agent'] or legacy_headers['user-agent']
   if agent and legacy_agent and agent~=legacy_agent then fail('conflicting_ws_user_agent') end
   n.user_agent=str(agent or legacy_agent)
  elseif network=='grpc' then
   n.transport='grpc';local opts=p['grpc-opts'] or {};known(opts,'grpc-service-name')
   n.serviceName=str(opts['grpc-service-name'])
  elseif network=='h2' then
   n.transport='h2';local opts=p['h2-opts'] or {};known(opts,'path host')
   n.h2_path=str(opts.path) or '/';local host=opts.host
   if type(host)=='table' then if #host>1 then fail('multiple_h2_hosts_not_supported') end;host=host[1] end
   n.h2_host=str(host)
  else fail('unsupported_vmess_transport') end
  for key,net in pairs({['ws-opts']='ws',['grpc-opts']='grpc',['h2-opts']='h2'}) do
   if p[key] and network~=net then fail('transport_options_mismatch') end
  end
  if (p['ws-path'] or p['ws-headers']) and network~='ws' then fail('transport_options_mismatch') end
 elseif kind=='hysteria2' then
  known(p,common..' password up down obfs obfs-password ports hop-interval')
  n.hy2_auth=str(p.password,true);tls(p,n,true)
  for _,v in ipairs({{'up','uplink_capacity'},{'down','downlink_capacity'}}) do
   if p[v[1]]~=nil then
    local speed=str(p[v[1]],true);local value=speed:match('^(%d+)%s*[Mm][Bb][Pp][Ss]$') or speed:match('^(%d+)$')
    if not value then fail('unsupported_bandwidth_unit') end;n[v[2]]=integer(value,0,1000000)
   end
  end
  if p.obfs and p.obfs~='none' and p.obfs~='' then
   if p.obfs~='salamander' then fail('unsupported_hysteria2_obfs') end
   n.flag_obfs='1';n.obfs_type='salamander';n.salamander=str(p['obfs-password'],true)
  elseif p['obfs-password'] then fail('obfs_password_without_obfs') end
  if p.ports then
   local ranges=str(p.ports,true);if ranges:find('[^%d,%-]') then fail('invalid_port_ranges') end
   for item in (ranges..','):gmatch('(.-),') do
    local a,b=item:match('^(%d+)%-(%d+)$');a=a or item;b=b or a
    integer(a,1,65535);integer(b,1,65535);if tonumber(a)>tonumber(b) then fail('invalid_port_ranges') end
   end
   n.flag_port_hopping='1';n.port_range=ranges
  end
  if p['hop-interval'] then
   local hop=str(p['hop-interval'],true);local a,b=hop:match('^(%d+)%-(%d+)$');a=a or hop;b=b or a
   integer(a,5,86400);integer(b,5,86400);if tonumber(a)>tonumber(b) then fail('invalid_hop_interval') end
   n.hopinterval=hop
  end
 else fail('unsupported_type:'..kind:gsub('[^%w_-]','?'):sub(1,32)) end
 return n
end
function M.signature(node)
 local keys={};for k in pairs(node) do if k~='hashkey' then keys[#keys+1]=k end end;table.sort(keys)
 local out={};for _,k in ipairs(keys) do local v=tostring(node[k]);out[#out+1]=#k..':'..k..#v..':'..v end
 return table.concat(out,'|')
end
function M.parse(raw,fetch)
 local lyaml=require('lyaml');local seen,providers={},0;local result={};local signatures={}
 local function document(text)
  if type(text)~='string' or #text==0 or #text>MAX_BYTES then fail('invalid_document_size') end
  local ok,doc=pcall(lyaml.load,text);if not ok or type(doc)~='table' then fail('invalid_yaml') end
  return doc
 end
 local function add(nodes)
  if nodes==nil then return end
  if type(nodes)~='table' then fail('invalid_proxies') end
  for _,p in ipairs(nodes) do
   local n=M.convert(p);local key=M.signature(n)
   if not signatures[key] then result[#result+1]=n;signatures[key]=true end
   if #result>MAX_NODES then fail('too_many_nodes') end
  end
 end
 local doc=document(raw);add(doc.proxies)
 if doc['proxy-providers'] then
  if type(doc['proxy-providers'])~='table' then fail('invalid_providers') end
  local names={};for k in pairs(doc['proxy-providers']) do names[#names+1]=k end;table.sort(names)
  for _,name in ipairs(names) do
   providers=providers+1;if providers>16 then fail('too_many_providers') end
   local p=doc['proxy-providers'][name];if type(p)~='table' then fail('invalid_provider') end
   known(p,'type url path interval header health-check proxy payload size-limit')
   if p.type=='inline' then add(p.payload)
   elseif p.type=='http' then
    local url=str(p.url,true);if not url:match('^https?://') or url:find('%s') then fail('invalid_provider_url') end
    local headers=p.header or {};known(headers,'User-Agent user-agent')
    local ua=headers['User-Agent'] or headers['user-agent'];if type(ua)=='table' then if #ua~=1 then fail('invalid_provider_user_agent') end;ua=ua[1] end;ua=str(ua)
    local cachekey=url..'\0'..(ua or '')
    if not seen[cachekey] then
     if not fetch then fail('provider_fetch_unavailable') end
     local data=fetch(url,ua);local child=document(data)
     if child['proxy-providers'] then fail('nested_provider_not_supported') end
     if not child.proxies then fail('provider_missing_proxies') end
     add(child.proxies);seen[cachekey]=true
    end
   else fail('unsupported_provider_type') end
  end
 end
 if #result==0 then fail('no_supported_nodes') end
 return result
end
return M
