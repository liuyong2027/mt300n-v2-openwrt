local module_path=assert(arg[1],'module path required')
local M=dofile(module_path)
local nixio=require('nixio')
local assertions=0
local function check(value,message)
    assertions=assertions+1
    assert(value,message)
end
local function snapshot(mode)
    return {board='cudy,tr3600-v1',mode=mode or 'split',id='generation-1',
        now=20,busy=false,uplink=0,ready=true,suspended=false,clock_ok=true,minute=600}
end
local before,after,codes,commands
M.blocked=function() return false end
M.snapshot=function() return after end
M.capture=function(command)
    commands[#commands+1]=command
    return codes[#commands] or ''
end
local function probe(mode,responses,change)
    before=snapshot(mode)
    after=snapshot(mode); after.now=21
    if change then change(before,after) end
    codes=responses; commands={}
    return M.probe(before)
end
local passed='target diagnostics\nMANGO_PROBE_OK'
local result=probe('split',{passed})
check(result and result.result==true,'common probe success must be accepted')
check(#commands==1 and commands[1]:find('/usr/libexec/mango-connectivity-probe split',1,true),
    'LED must invoke the common script once with the current mode')
check(not commands[1]:find('curl',1,true) and not commands[1]:find('https://',1,true),
    'LED must not retain a second HTTP implementation')
result=probe('global',{'target failed'})
check(result and result.result==false,'common script failure must be rejected')
result=probe('global',{'MANGO_PROBE_OK'})
check(result and result.result==false,'success requires the command exit marker boundary')
result=probe('global',{'details\nMANGO_PROBE_OK\nextra'})
check(result and result.result==false,'a marker in ordinary diagnostics must not imply success')
result=probe('gfw',{passed})
check(result and result.result==true and commands[1]:find('mango-connectivity-probe gfw',1,true),
    'GFW mode must be delegated to the common script')
result=probe('direct',{passed})
check(result and result.result==true and commands[1]:find('mango-connectivity-probe direct',1,true),
    'direct mode must be delegated to the common script')
result=probe('split',{passed},function(_,s) s.id='generation-2' end)
check(result==nil,'changed runtime identity must invalidate a result')
result=probe('split',{passed},function(_,s) s.mode='direct' end)
check(result==nil,'changed mode must invalidate a result')
result=probe('split',{passed},function(_,s) s.busy=true end)
check(result==nil,'concurrent reconfiguration must invalidate a result')
result=probe('split',{passed},function(_,s) s.uplink=1 end)
check(result==nil,'lost uplink must invalidate a result')
result=probe('split',{passed},function(_,s) s.ready=false end)
check(result==nil,'lost proxy readiness must invalidate a result')
result=probe('split',{passed},function(s) s.busy=true end)
check(result==nil and #commands==0,'busy runtime must not be probed')
result=probe('split',{passed},function(s) s.ready=false end)
check(result==nil and #commands==0,'unready proxy must not be probed')
result=probe('split',{passed},function(s) s.failover=true end)
check(result==nil and #commands==0,'enabled failover must own proxy probing exclusively')
result=probe('split',{passed},function(_,s) s.failover=true end)
check(result==nil,'enabling failover during an LED probe must discard the result')
result=probe('direct',{passed},function(s,a) s.failover=true; a.failover=true end)
check(result and result.result==true,'direct mode must retain LED probes even with failover enabled')

local function run_schedule(mode,light_mode,change_identity)
    M=dofile(module_path)
    local now,probes,frames,writes=0,{},{},{}
    nixio.nanosleep=function(seconds) now=now+seconds end
    M.config=function() return {mode=light_mode or 'status',night='0'} end
    M.blocked=function() return now>=(change_identity and 220 or 145) end
    M.save_leds=function() return true end
    M.read=function() error('LED loop must not consume watchdog probe files') end
    M.snapshot=function()
        local s=snapshot(mode); s.now=now
        if change_identity and now>=90 then s.id='generation-2' end
        return s
    end
    M.probe=function(s)
        probes[#probes+1]=s.now
        return {id=s.id,at=s.now,key='test:'..s.now,result=true}
    end
    M.atomic=function(path,value)
        writes[#writes+1]={path=path,value=value}
        return true
    end
    M.apply=function(frame)
        frames[#frames+1]=frame.state
        return true
    end
    M.run()
    return probes,frames,writes
end
for _,mode in ipairs({'direct','split','global','gfw'}) do
    local probes,frames,writes=run_schedule(mode)
    check(#probes==3 and probes[1]==15 and probes[2]==75 and probes[3]==135,
        mode..': LED must independently probe every 60 seconds')
    check(frames[1]=='unknown' and frames[2]=='healthy' and #frames==2,
        mode..': two successful observations must produce steady white')
    check(#writes==3 and writes[1].path:match('/connectivity%.json$'),
        mode..': independent observations must be available for diagnosis')
end
local probes,frames=run_schedule('split','off')
check(#probes==0 and frames[1]=='off','lights-off mode must not generate probes')
probes,frames=run_schedule('split','status',true)
check(probes[3]==90,'identity change must trigger a fresh probe immediately')
check(table.concat(frames,',')=='unknown,healthy,unknown,healthy',
    'identity change must discard old confirmations')

local function run_sources(kind,mode)
    M=dofile(module_path)
    local now,owned,frames,writes,reads=0,{},{},{},0
    local stop=kind=='toggle' and 280 or 145
    local function enabled()
        return kind~='toggle' or (now>=90 and now<180)
    end
    nixio.nanosleep=function(seconds) now=now+seconds end
    M.config=function() return {mode='status',night='0'} end
    M.blocked=function() return now>=stop end
    M.save_leds=function() return true end
    M.snapshot=function()
        local s=snapshot(mode); s.now=now; s.failover=enabled()
        return s -- Keep identity fixed to exercise explicit source transitions.
    end
    M.probe=function(s)
        check(not s.failover or s.mode=='direct','LED must not probe when watchdog owns proxy checks')
        owned[#owned+1]=now
        return {id=s.id,at=now,key='led:'..now,result=true}
    end
    M.read=function(path)
        reads=reads+1
        check(path==M.dir..'/proxy.json','shared source must read the existing watchdog result')
        if kind=='missing' then return nil end
        local start=kind=='toggle' and 90 or 15
        local at=start+math.floor((now-start)/60)*60
        if kind=='stale' then at=10 end
        return {id='generation-1',at=at,key='watchdog:'..at,result=kind~='failed'}
    end
    M.atomic=function(path,value)
        writes[#writes+1]=value.source
        return true
    end
    M.apply=function(frame) frames[#frames+1]=frame.state; return true end
    M.run()
    return owned,frames,writes,reads
end
local owned,writes,reads
owned,frames,writes,reads=run_sources('shared')
check(#owned==0 and reads>0,'shared mode must consume results without issuing LED requests')
check(table.concat(frames,',')=='unknown,healthy','shared successes must turn white steady')
check(#writes==3 and writes[1]=='watchdog','diagnostics must identify watchdog-owned results')
owned,frames=run_sources('failed')
check(#owned==0 and frames[#frames]=='failed','three shared failures must produce flashing red')
owned,frames=run_sources('missing')
check(#owned==0 and table.concat(frames,',')=='unknown','missing shared results must wait without duplicate probes')
owned,frames=run_sources('stale')
check(#owned==0 and table.concat(frames,',')=='unknown','pre-transition shared observations must not be accepted')
owned,frames,writes,reads=run_sources('shared','direct')
check(#owned==3 and reads==0,'direct mode must never depend on watchdog observations')
check(frames[#frames]=='healthy' and writes[1]=='led','direct mode diagnostics must identify LED source')
owned,frames=run_sources('toggle')
check(table.concat(owned,',')=='15,75,180,240','enabling must stop LED probes and disabling must resume immediately')
check(table.concat(frames,',')=='unknown,healthy,unknown,healthy,unknown,healthy',
    'each source transition must require fresh confirmations')

M=dofile(module_path)
local s=snapshot('split')
M.config=function() return {mode='status'} end
M.blocked=function() return false end
M.snapshot=function() return s end
M.atomic=function() return true end
check(M.begin()==nil,'disabled failover must not create shared observation tokens')
s.failover=true
local token=M.begin()
check(token~=nil and M.finish(token,true),'enabled failover callbacks must publish shared results')
s.failover=false
check(not M.finish(token,true),'disabling failover must reject an outstanding shared result')
print('PASS '..assertions..' assertions: probe ownership, live source changes, shared results, and connectivity guards')
