local fs=require('nixio.fs')
local nixio=require('nixio')
local json=require('luci.jsonc')
local uci=require('uci')
local engine=require('cudy.led')
local M={dir='/var/run/cudy-led'}
local names={'white:status','red:status'}
local attrs={'delay_on','delay_off','device_name','interval','link','rx','tx','pattern'}
local function trim(s) return (s or ''):gsub('%s+$','') end
function M.capture(command)
    local p=io.popen(command..' 2>/dev/null'); if not p then return '' end
    local out=p:read('*a') or ''; p:close(); return trim(out)
end
function M.board() return trim(fs.readfile('/tmp/sysinfo/board_name')) end
function M.now() return tonumber((fs.readfile('/proc/uptime') or ''):match('^[%d.]+')) or 0 end
function M.blocked()
    return fs.access(M.dir..'/suspend') or fs.access(M.dir..'/stopped') or fs.access('/tmp/.failsafe')
end
function M.config() return engine.config(uci.cursor():get_all('cudy_led','main')) end
function M.atomic(path,value)
    fs.mkdir(M.dir); fs.chmod(M.dir,'700')
    local tmp=path..'.'..nixio.getpid()..'.new'
    if not fs.writefile(tmp,'') or not fs.chmod(tmp,'600') then return false end
    if not fs.writefile(tmp,json.stringify(value)) then fs.remove(tmp); return false end
    if not fs.rename(tmp,path) then fs.remove(tmp); return false end
    return true
end
function M.read(path)
    local s=fs.readfile(path)
    if not s or #s > 8192 then return end
    return json.parse(s)
end
local function hash(command)
    local s=M.capture(command..' | sha256sum'):match('^(%x+)')
    return s and #s==64 and s or nil
end
function M.uplink_data()
    -- Only default exits affect Internet health. LAN carrier changes and unrelated
    -- USB/network interfaces must not discard successful proxy observations.
    local routes=M.capture('ip -4 route show table main default'):gsub(' expires %S+','')
    local out={routes}; local devices={}
    for dev in routes:gmatch('%f[%w]dev%s+(%S+)') do
        if not dev:match('^[%w_.:%-]+$') then
            out[#out+1]='invalid-device'
        else devices[dev]=true end
    end
    local ordered={}; for dev in pairs(devices) do ordered[#ordered+1]=dev end
    table.sort(ordered)
    for _,dev in ipairs(ordered) do
        local link=M.capture('ip -o link show dev '..dev)
        local addresses=M.capture('ip -o -4 addr show dev '..dev..' scope global')
        local inet={}; for address in addresses:gmatch('%f[%w]inet%s+(%S+)') do inet[#inet+1]=address end
        table.sort(inet) -- Lease countdowns and address output order are irrelevant.
        out[#out+1]=dev..'|'..(link:match('<([^>]*)>') or 'unknown')..'|'..
            trim(fs.readfile('/sys/class/net/'..dev..'/operstate'))..'|'..
            trim(fs.readfile('/sys/class/net/'..dev..'/carrier'))..'|'..table.concat(inet,',')
    end
    return table.concat(out,'\n')
end
function M.identity()
    local runtime=hash('/usr/libexec/mango-runtime-id')
    local config=hash('uci -q export mango_proxy')
    local data=M.uplink_data():gsub("'", "'\\''")
    local uplink=hash("printf '%s' '"..data.."'")
    if runtime and config and uplink then return runtime..':'..config..':'..uplink end
end
function M.snapshot()
    local saved=M.capture('uci -q get mango_proxy.main.mode')
    local mode=(fs.readfile('/var/etc/mango/runtime-state') or ''):match('^([^\r\n]+)')
    local busy=os.execute('flock -n /var/lock/mango-operation.lock true >/dev/null 2>&1') ~= 0
    local status=os.execute('/usr/libexec/mango-uplink >/dev/null 2>&1')
    local uplink=status==0 and 0 or (status==256 and 1 or 2)
    -- Lua 5.1 os.execute returns the wait status, not an unshifted exit code.
    return {board=M.board(),now=M.now(),id=M.identity(),mode=mode,
        failover=M.capture('uci -q get mango_proxy.main.failover')=='1',
        busy=busy or mode ~= saved or fs.access('/var/etc/mango/runtime-uncertain'),uplink=uplink,
        ready=mode == 'direct' or os.execute('/usr/libexec/mango-ready >/dev/null 2>&1')==0,
        suspended=M.blocked(),clock_ok=fs.access(M.dir..'/clock-synced') and os.time()>1704067200,
        minute=tonumber(os.date('%H'))*60+tonumber(os.date('%M'))}
end
function M.source(s)
    if s.failover and ({split=true,global=true,gfw=true})[s.mode] then return 'watchdog' end
    return 'led'
end
function M.begin()
    local c=M.config()
    if M.board() ~= 'cudy,tr3600-v1' or M.blocked() or not c or c.mode ~= 'status' then return end
    local s=M.snapshot()
    if s.busy or s.uplink ~= 0 or not s.id or M.source(s) ~= 'watchdog' then return end
    return {id=s.id,at=s.now,key=s.now..':'..nixio.getpid()}
end
function M.finish(token,result)
    if type(token) ~= 'table' or type(token.at) ~= 'number' or type(token.key) ~= 'string' or
       type(token.id) ~= 'string' or M.board()~='cudy,tr3600-v1' or M.blocked() then return false end
    local s=M.snapshot()
    if token.id ~= s.id or s.busy or s.uplink ~= 0 or M.source(s) ~= 'watchdog' or
       token.at > s.now or s.now-token.at > 30 then return false end
    return M.atomic(M.dir..'/proxy.json',{id=s.id,at=s.now,key=token.key,result=result})
end
function M.probe(before)
    local direct=before.mode=='direct'
    if not direct and not ({split=true,global=true,gfw=true})[before.mode] then return end
    if M.source(before) ~= 'led' or not before.id or before.busy or before.uplink ~= 0 or
       (not direct and not before.ready) or M.blocked() then return end
    local report=M.capture('/usr/libexec/mango-connectivity-probe '..before.mode..
        " && printf '\\nMANGO_PROBE_OK'")
    local ok=report:match('\nMANGO_PROBE_OK$') ~= nil
    local after=M.snapshot()
    if before.id ~= after.id or after.mode ~= before.mode or M.source(after) ~= 'led' or
       after.busy or after.uplink ~= 0 or
       (not direct and not after.ready) or M.blocked() then return end
    return {id=after.id,at=after.now,key='led:'..after.mode..':'..before.now,result=ok}
end
local function root(name) return '/sys/class/leds/'..name..'/' end
local function valid_backup(backup)
    if type(backup)~='table' then return false end
    for _,name in ipairs(names) do
        local v=backup[name]
        if type(v)~='table' or type(v.attrs)~='table' or type(v.trigger)~='string' or
           not v.trigger:match('^[%w:_%-]+$') or (v.brightness~='0' and v.brightness~='1') then return false end
        for _,attr in ipairs(attrs) do
            if v.attrs[attr] ~= nil and (type(v.attrs[attr])~='string' or #v.attrs[attr]>4096) then return false end
        end
    end
    return true
end
function M.save_leds()
    if M.board() ~= 'cudy,tr3600-v1' or M.blocked() then return false end
    if fs.access(M.dir..'/backup.json') then return valid_backup(M.read(M.dir..'/backup.json')) end
    local backup={}
    for _,name in ipairs(names) do
        local trigger=(fs.readfile(root(name)..'trigger') or ''):match('%[([^%]]+)%]')
        local brightness=trim(fs.readfile(root(name)..'brightness'))
        if not trigger or not brightness:match('^[01]$') then return false end
        local data={trigger=trigger,brightness=brightness,attrs={}}
        for _,attr in ipairs(attrs) do
            local value=fs.readfile(root(name)..attr)
            if value then data.attrs[attr]=trim(value) end
        end
        backup[name]=data
    end
    return M.atomic(M.dir..'/backup.json',backup)
end
function M.restore()
    if M.board() ~= 'cudy,tr3600-v1' or fs.access(M.dir..'/suspend') or fs.access('/tmp/.failsafe') then return true end
    if not fs.access(M.dir..'/backup.json') then return true end
    local backup=M.read(M.dir..'/backup.json'); if not valid_backup(backup) then return false end
    local ok=true
    for _,name in ipairs(names) do
        local v=backup[name]
        ok=fs.writefile(root(name)..'trigger','none') and ok
        ok=fs.writefile(root(name)..'brightness',v.brightness) and ok
        ok=fs.writefile(root(name)..'trigger',v.trigger) and ok
        for _,attr in ipairs(attrs) do
            if v.attrs[attr] ~= nil and fs.access(root(name)..attr) then
                ok=type(v.attrs[attr])=='string' and fs.writefile(root(name)..attr,v.attrs[attr]) and ok
            end
        end
    end
    if ok then fs.remove(M.dir..'/backup.json') end
    return not not ok
end
function M.apply(frame)
    if frame.release or M.blocked() or M.board() ~= 'cudy,tr3600-v1' then return true end
    local ok=true
    for _,name in ipairs(names) do
        local pattern=name=='white:status' and frame.white or frame.red
        ok=fs.writefile(root(name)..'trigger','none') and ok
        ok=fs.writefile(root(name)..'brightness',pattern=='on' and '1' or '0') and ok
        if pattern=='slow' or pattern=='wait' then
            ok=fs.writefile(root(name)..'trigger','timer') and ok
            ok=fs.writefile(root(name)..'delay_on',pattern=='slow' and '1000' or '500') and ok
            ok=fs.writefile(root(name)..'delay_off',pattern=='slow' and '1000' or '1500') and ok
        end
    end
    return not not ok
end
function M.run()
    -- Normal rcS completes its own LED setup after launching the last service.
    nixio.nanosleep(15)
    local c=M.config(); if not c or M.blocked() or c.mode=='default' then return end
    if not M.save_leds() then error('无法保存原有指示灯状态，未接管灯光') end
    local memory,last={},nil
    local sample,last_probe=nil,-60
    local source,last_recorded=nil,nil
    while not M.blocked() do
        local s=M.snapshot()
        -- Exactly one probe producer is active in each steady operating mode.
        local selected=M.source(s)
        if source~=selected then
            source=selected; memory={}; last_recorded=nil
        end
        if memory.id~=s.id or memory.mode~=s.mode or not memory.since then
            engine.step(memory,c,s)
            sample=nil; last_probe=-60; last_recorded=nil
        end
        local supported=s.mode=='direct' or ({split=true,global=true,gfw=true})[s.mode]
        if source=='watchdog' then
            sample=M.read(M.dir..'/proxy.json')
        elseif c.mode=='status' and supported and not s.busy and s.uplink==0 and
           (s.mode=='direct' or s.ready) then
            if s.now-last_probe>=60 then
                last_probe=s.now; sample=M.probe(s); s=M.snapshot()
            end
        else
            sample=nil; last_probe=-60
        end
        s.sample=sample
        local frame=engine.step(memory,c,s)
        if frame.release then break end
        if type(sample)=='table' and sample.id==s.id and type(sample.key)=='string' and
           type(sample.at)=='number' and sample.at>=memory.since and sample.at<=s.now and
           (sample.result==true or sample.result==false) and sample.key~=last_recorded then
            if M.atomic(M.dir..'/connectivity.json',{id=sample.id,at=sample.at,key=sample.key,
                result=sample.result,source=source}) then last_recorded=sample.key end
        end
        local key=frame.state..':'..frame.white..':'..frame.red
        if key~=last then
            if not M.apply(frame) then error('指示灯写入失败') end
            last=key
        end
        nixio.nanosleep(5)
    end
end
return M
