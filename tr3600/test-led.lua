-- Deterministic fixtures; no real router config, sockets or LEDs are accessed.
local e=dofile(arg[1] or 'tr3600/luci-app-cudy-led/root/usr/lib/lua/cudy/led.lua')
local count=0
local function test(name,fn) fn(); count=count+1; print('PASS '..name) end
local function fixture()
    local c=assert(e.config())
    local s={board='cudy,tr3600-v1',now=0,id='runtime:config:uplink',mode='global',uplink=0,ready=true,clock_ok=true,minute=720}
    local m={}; e.step(m,c,s)
    return m,c,s
end
local function round(m,c,s,at,result)
    s.now=at; s.sample={id=s.id,key='round:'..at,at=at,result=result}
    return e.step(m,c,s)
end
test('recommended default and night disabled',function()
    local c=assert(e.config()); assert(c.mode=='status' and c.night=='0' and c.first==1380 and c.last==420)
end)
test('normal requires two different successful rounds',function()
    local m,c,s=fixture(); assert(round(m,c,s,60,true).white=='wait')
    assert(round(m,c,s,120,true).white=='on' and e.step(m,c,s).red=='off')
end)
test('polling one report repeatedly never counts as another success',function()
    local m,c,s=fixture(); round(m,c,s,60,true); s.now=65
    for i=1,20 do assert(e.step(m,c,s).state=='unknown') end
end)
test('three failed rounds produce red slow flash',function()
    local m,c,s=fixture(); assert(round(m,c,s,60,false).state=='unknown')
    assert(round(m,c,s,120,false).state=='unknown'); assert(round(m,c,s,180,false).red=='slow')
end)
test('two recovery successes required; first keeps fault red',function()
    local m,c,s=fixture(); for i=1,3 do round(m,c,s,i*60,false) end
    assert(round(m,c,s,240,true).red=='slow'); assert(round(m,c,s,300,true).white=='on')
end)
test('one failure clears the previously healthy indication',function()
    local m,c,s=fixture(); round(m,c,s,60,true); round(m,c,s,120,true)
    assert(round(m,c,s,180,false).state=='unknown')
end)
test('WAN outage has ten-second debounce and solid red',function()
    local m,c,s=fixture(); s.uplink=1; s.now=20; assert(e.step(m,c,s).state=='unknown')
    s.now=29; assert(e.step(m,c,s).red=='off'); s.now=30; assert(e.step(m,c,s).red=='on')
end)
test('WAN reconnect discards pre-outage healthy report',function()
    local m,c,s=fixture(); round(m,c,s,60,true); round(m,c,s,120,true)
    s.now=130; s.uplink=1; e.step(m,c,s); s.now=140; e.step(m,c,s)
    s.now=150; s.uplink=0; assert(e.step(m,c,s).state=='unknown')
end)
for _,field in ipairs({'runtime','config','uplink'}) do
    test('changing '..field..' identity invalidates old reports',function()
        local m,c,s=fixture(); round(m,c,s,60,true); round(m,c,s,120,true)
        s.now=130; s.id='different-'..field; assert(e.step(m,c,s).state=='unknown')
    end)
end
test('success report expires; no stale healthy light',function()
    local m,c,s=fixture(); round(m,c,s,60,true); round(m,c,s,120,true)
    s.now=271; assert(e.step(m,c,s).state=='unknown')
end)
test('failed report survives watchdog backoff but expires eventually',function()
    local m,c,s=fixture(); for i=1,3 do round(m,c,s,i*60,false) end
    s.now=700; assert(e.step(m,c,s).red=='slow'); s.now=841; assert(e.step(m,c,s).state=='unknown')
end)
test('applying/uncertain and unknown uplink never show healthy',function()
    for _,flag in ipairs({'busy','uplink'}) do
        local m,c,s=fixture(); round(m,c,s,60,true); round(m,c,s,120,true)
        if flag=='busy' then s.busy=true else s.uplink=2 end
        assert(e.step(m,c,s).state=='unknown')
    end
end)
test('direct mode uses direct reports and does not require Xray',function()
    local m,c,s=fixture(); s.mode='direct'; s.ready=false; s.now=1; e.step(m,c,s)
    round(m,c,s,60,true); assert(round(m,c,s,120,true).state=='healthy')
end)
test('mode switch resets failure counters',function()
    local m,c,s=fixture(); round(m,c,s,60,false); round(m,c,s,120,false)
    s.mode='direct'; s.now=121; e.step(m,c,s); assert(round(m,c,s,180,false).red=='off')
end)
test('dead core gets startup grace then three local failure rounds',function()
    local m,c,s=fixture(); s.ready=false; s.now=179; assert(e.step(m,c,s).state=='unknown')
    s.now=180; e.step(m,c,s); s.now=240; e.step(m,c,s); s.now=300; assert(e.step(m,c,s).red=='slow')
end)
test('no probes means unknown, not healthy or assumed proxy failure',function()
    local m,c,s=fixture(); s.now=500; assert(e.step(m,c,s).state=='unknown')
end)
for _,case in ipairs({'suspended','failsafe','wrong-board'}) do
    test(case..' releases LEDs to the system',function()
        local m,c,s=fixture(); if case=='wrong-board' then s.board='other,device' else s[case]=true end
        assert(e.step(m,c,s).release)
    end)
end
test('system-default and daily-off modes',function()
    local m,c,s=fixture(); c.mode='default'; assert(e.step(m,c,s).release)
    c.mode='off'; local f=e.step(m,c,s); assert(f.white=='off' and f.red=='off')
end)
test('night crossing midnight has exact start/end boundaries',function()
    local m,c,s=fixture(); c.night='1'
    for minute,expected in pairs({[1379]=false,[1380]=true,[1439]=true,[0]=true,[419]=true,[420]=false}) do
        s.minute=minute; assert(e.night(c,s)==expected)
    end
end)
test('same-day night interval and unsynchronized clock',function()
    local c=assert(e.config({night='1',night_start='08:00',night_end='10:00'}))
    assert(e.night(c,{clock_ok=true,minute=480})); assert(not e.night(c,{clock_ok=true,minute=600}))
    assert(not e.night(c,{clock_ok=false,minute=500}))
end)
test('night suppresses white but preserves fault red',function()
    local m,c,s=fixture(); c.night='1'; s.minute=0
    round(m,c,s,60,true); assert(round(m,c,s,120,true).white=='off')
    for i=3,5 do round(m,c,s,i*60,false) end
    assert(e.step(m,c,s).red=='slow')
end)
test('future, malformed and prior-boot reports are rejected',function()
    for _,p in ipairs({{id='runtime:config:uplink',key='future',at=500,result=true},
        {id='runtime:config:uplink',key='old',at=-1,result=true},{id='bad',key='x',at=1,result=true},
        {id='runtime:config:uplink',key='invalid',at=1,result='yes'}}) do
        local m,c,s=fixture(); s.now=2; s.sample=p; assert(e.step(m,c,s).state=='unknown')
    end
end)
test('invalid modes/time/flags rejected',function()
    for _,raw in ipairs({{mode='shell;bad'},{night='2'},{night_start='24:00'},
        {night_end='7:00'},{night_start='07:00',night_end='07:00'}}) do assert(not e.config(raw)) end
end)
print('LED state/identity/debounce/night/lifecycle: '..count..' tests passed')
