#!/usr/bin/lua
local fs=require('nixio.fs')
local n=require('nixio')
local j=require('luci.jsonc')
local M=dofile('/usr/lib/mango/ss-zt.lua')
local run='/var/run/cudy-ss-ui'
local function output(ok,result,message)
    io.write(j.stringify(ok and {ok=true,result=result} or {ok=false,message=message}),'\n')
end
local function capture(command)
    local p=io.popen(command); if not p then return '' end
    local s=p:read('*a'); p:close(); return s
end
local function quote(s) return "'"..s:gsub("'","'\\''").."'" end
local function raw() return require('uci').cursor():get_all('cudy_ss','main') or {} end
local function busy()
    return fs.access(run..'/pending.json') or os.execute('flock -n /var/lock/cudy-ss-ui-job.lock true >/dev/null 2>&1')~=0
end
if arg[1]=='list' then
    io.write('{"status":{},"configure":{"enabled":true,"port":8388,"method":"","password":""},"client":{}}\n')
    os.exit(0)
end
if arg[1]~='call' then os.exit(2) end
local input=io.read(8193) or ''
if #input>8192 then output(false,nil,'请求过大'); os.exit(0) end
local params=j.parse(input)
if type(params)~='table' then output(false,nil,'请求格式错误'); os.exit(0) end
params.ubus_rpc_session=nil
local action=arg[2]
if action=='status' then
    local networks=j.parse(capture('timeout 3 zerotier-cli -j listnetworks 2>/dev/null')) or {}
    local r=M.select(raw(),networks)
    local ok,c=pcall(M.scope,r)
    local online=ok and M.available(c,networks) or false
    local name='ZeroTier'
    for _,net in ipairs(networks) do if net.id==r.network_id then name=net.name or name end end
    local state=j.parse(fs.readfile(run..'/status.json') or '') or {}
    local applying=busy()
    output(true,{enabled=r.enabled=='1',port=tonumber(r.port) or 8388,method=r.method or 'aes-128-gcm',
        listen=r.listen or '',subnet=r.subnet or '',network_name=name,network_online=online,
        ready=r.enabled=='1' and online and os.execute('/usr/libexec/cudy-ss-zt available >/dev/null 2>&1')==0 and
            os.execute('/usr/libexec/cudy-ss-zt ready >/dev/null 2>&1')==0 or false,
        applying=applying,error=state.error or '',password_set=type(r.password)=='string' and #r.password>=24})
elseif action=='configure' then
    if busy() then output(false,nil,'已有设置正在应用，请稍候'); os.exit(0) end
    local networks=j.parse(capture('timeout 3 zerotier-cli -j listnetworks 2>/dev/null')) or {}
    local ok,candidate=pcall(M.request,raw(),params,networks)
    if not ok then output(false,nil,'设置无效：请检查端口、加密方式和密码（24–128 字符）'); os.exit(0) end
    fs.mkdir(run); assert(fs.chmod(run,'700'))
    local dir=run..'/request.'..n.getpid()
    if not fs.mkdir(dir) then output(false,nil,'无法暂存请求'); os.exit(0) end
    assert(fs.chmod(dir,'700'))
    local file=dir..'/candidate.json'
    local written=fs.writefile(file,j.stringify(candidate)) and fs.chmod(file,'600')
    local accepted=written and os.execute('/usr/libexec/cudy-ss-job queue '..quote(dir)..' >/dev/null 2>&1')==0
    fs.remove(file); fs.rmdir(dir)
    if accepted then output(true,{applying=true,message='已提交设置，正在校验并应用。'})
    else output(false,nil,'无法提交：已有任务或暂存失败，请稍后重试') end
elseif action=='client' then
    if busy() then output(false,nil,'设置正在应用，请稍候'); os.exit(0) end
    local ok,c=pcall(M.validate,raw())
    if not ok or not c then output(false,nil,'服务未启用或配置无效'); os.exit(0) end
    local credentials=n.bin.b64encode(c.method..':'..c.password):gsub('=+$',''):gsub('%+','-'):gsub('/','_')
    output(true,{server=c.listen,port=c.port,method=c.method,password=c.password,
        uri='ss://'..credentials..'@'..c.listen..':'..c.port..'#TR3600-ZeroTier'})
else output(false,nil,'未知操作') end
