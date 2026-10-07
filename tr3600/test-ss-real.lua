-- Actual ARM64 UCI/nixio/jsonc with disposable paths. Service, network metadata,
-- process identity and nft actions are replaced; this is not a hardware reboot.
local fs=require('nixio.fs');local n=require('nixio');local j=require('luci.jsonc');local U=require('uci')
local base=assert(os.getenv('CUDY_SS_TEST_DIR'));local source=assert(os.getenv('CUDY_SS_SOURCE'))
assert(base:match('^/tmp/cudy%-ss%-[%w]+$'))
local prefix=source..'/luci-app-cudy-ss/root'
assert(fs.chmod(base,'700'))
for _,d in ipairs({'config','ucisave','private','run'}) do assert(fs.mkdir(base..'/'..d));assert(fs.chmod(base..'/'..d,'700')) end
assert(fs.writefile(base..'/config/cudy_ss',assert(fs.readfile(prefix..'/etc/config/cudy_ss'))));assert(fs.chmod(base..'/config/cudy_ss','600'))
local M=dofile(prefix..'/usr/lib/mango/ss-zt.lua')
local initial={enabled='1',port='8388',method='aes-128-gcm',password=string.rep('F',32),listen='192.168.77.6',subnet='192.168.77.0/24',interface='ztfixture01',network_id='0123456789abcdef'}
local u=U.cursor(base..'/config',base..'/ucisave');for k,v in pairs(initial) do assert(u:set('cudy_ss','main',k,v)) end;assert(u:commit('cudy_ss'))
local networks={{id=initial.network_id,type='PRIVATE',status='OK',portDeviceName=initial.interface,assignedAddresses={initial.listen..'/24'}}}
local function root(path)
    local map={['/etc/config/cudy_ss']=base..'/config/cudy_ss',['/etc/cudy-ss']=base..'/private',['/var/run/cudy-ss-ui']=base..'/run',['/var/etc/mango/config.json']=base..'/core.json'}
    for before,after in pairs(map) do if path==before or path:sub(1,#before+1)==before..'/' or path:sub(1,#before+5)==before..'.new.' then return after..path:sub(#before+1) end end
    return path
end
local proxy={}
for _,name in ipairs({'access','mkdir','rmdir','remove','readfile','writefile','chmod'}) do proxy[name]=function(path,...) if path:match('^/proc/net/') then return '' end;return fs[name](root(path),...) end end
proxy.rename=function(a,b) return fs.rename(root(a),root(b)) end
proxy.realpath=function(path) if path=='/var/lock/mango-operation.lock' then return base..'/lock' end;return fs.realpath(root(path)) end
proxy.readlink=function(path) if path=='/proc/self/fd/9' then return base..'/lock' end;return fs.readlink(root(path)) end
local cursor={cursor=function(conf,save)
    if not conf then return U.cursor(base..'/config',base..'/ucisave') end
    return U.cursor(root(conf),root(save))
end}
local plain={inbounds={{tag='local',listen='127.0.0.1',port=10808,protocol='socks',settings={udp=true}}},outbounds={{tag='direct',protocol='freedom'}}}
local function runtime()
    local copy=j.parse(j.stringify(plain));local c=M.validate(U.cursor(base..'/config',base..'/ucisave'):get_all('cudy_ss','main'))
    M.augment(copy,c,c and M.available(c,networks));assert(fs.writefile(base..'/core.json',j.stringify(copy)))
end
runtime()
local original_dofile,original_exec,original_popen,original_exit,original_arg=dofile,os.execute,io.popen,os.exit,arg
local fail_reload=false
package.loaded['nixio.fs']=proxy;package.loaded['uci']=cursor
dofile=function(path) if path=='/usr/lib/mango/ss-zt.lua' then return M elseif path=='/usr/lib/mango/ss-transaction.lua' then return original_dofile(prefix..'/usr/lib/mango/ss-transaction.lua') end;return original_dofile(path) end
io.popen=function(cmd)
 local text=''
 if cmd:find('listnetworks',1,true) then text=j.stringify(networks)
 elseif cmd:find('mango-generate.cudy-ss-base',1,true) then text=j.stringify(plain)
 elseif cmd:find('mango-process snapshot',1,true) then text='123:456\n' end
 return {read=function()return text end,close=function()return true end}
end
os.execute=function(cmd)
 if cmd:find('/etc/init.d/mango_proxy reload',1,true) then
  if fail_reload then fail_reload=false;return 1 end
  runtime();return 0
 end
 return 0
end
os.exit=function(code) error({exit=code}) end
local getenv=os.getenv;os.getenv=function(key) if key=='MANGO_OPERATION_LOCK' then return '1' end;return getenv(key) end
local function apply(enabled,port)
    local r=U.cursor(base..'/config',base..'/ucisave'):get_all('cudy_ss','main')
    local candidate=M.request(r,{enabled=enabled,port=port,method='aes-128-gcm',password=''},networks)
    assert(fs.writefile(base..'/run/pending.json',j.stringify(candidate)))
    arg={};local ok,e=pcall(original_dofile,prefix..'/usr/libexec/cudy-ss-worker')
    assert(not ok and type(e)=='table' and type(e.exit)=='number','Unexpected worker error')
    assert(not fs.access(base..'/run/pending.json'))
    return e.exit,j.parse(fs.readfile(base..'/run/status.json'))
end
local rc=apply(true,8389);assert(rc==0);local current=U.cursor(base..'/config',base..'/ucisave'):get_all('cudy_ss','main');assert(current.port=='8389' and current.password==initial.password)
assert(not fs.access(base..'/private/ui-transaction'))
assert(apply(false,8389)==0);assert(M.matches(j.parse(fs.readfile(base..'/core.json')),nil,false))
assert(apply(true,8388)==0)
fail_reload=true;local rc,status=apply(true,8389);assert(rc==1 and status.rollback==true)
current=U.cursor(base..'/config',base..'/ucisave'):get_all('cudy_ss','main');assert(current.port=='8388' and current.password==initial.password)
assert(M.matches(j.parse(fs.readfile(base..'/core.json')),M.validate(current),true))
-- Real access bits: no numeric chmod adapter can conceal production mistakes.
assert(fs.stat(base..'/config/cudy_ss','modestr')=='rw-------')
assert(fs.stat(base..'/run','modestr')=='rwx------')
package.loaded['nixio.fs']=fs;package.loaded['uci']=U;dofile=original_dofile;os.execute=original_exec;io.popen=original_popen;os.exit=original_exit;os.getenv=getenv;arg=original_arg
print('PASS actual ARM64 UCI commit/reopen + private nixio modes + production SS worker port/disable/enable/reload-failure rollback; service/nft replaced')
