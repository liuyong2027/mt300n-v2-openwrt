-- Isolated OS/UCI/sysfs mocks; do not open real LEDs or sockets.
local real_execute=os.execute
local files,writes,fail={}, {}, nil
local sequence,objects=0,{}
local json={}
function json.stringify(v) sequence=sequence+1; local key='json:'..sequence; objects[key]=v; return key end
function json.parse(v) return objects[v] end
local fs={}
function fs.readfile(p) return files[p] end
function fs.access(p) return files[p]~=nil end
function fs.mkdir(p) return true end
function fs.chmod(p,mode) assert(type(mode)=='string' and (mode=='600' or mode=='700')); return true end
function fs.writefile(p,v)
    writes[#writes+1]={p,v}
    if p==fail then return false end
    files[p]=v; return true
end
function fs.rename(a,b) if b==fail then return false end; files[b]=files[a]; files[a]=nil; return true end
function fs.remove(p) files[p]=nil; return true end
local raw={mode='status',night='0'}
local uc={}; function uc:get_all(c,s) assert(c=='cudy_led' and s=='main'); return raw end
local sleeps=0
package.loaded['nixio.fs']=fs
package.loaded['nixio']={getpid=function() return 42 end,nanosleep=function(n)
    sleeps=sleeps+1; if sleeps>2 then files['/var/run/cudy-led/stopped']='1' end
end}
package.loaded['luci.jsonc']=json
package.loaded['uci']={cursor=function() return uc end}
package.loaded['cudy.led']=dofile(arg[1] or 'tr3600/luci-app-cudy-led/root/usr/lib/lua/cudy/led.lua')
local R=dofile(arg[2] or 'tr3600/luci-app-cudy-led/root/usr/lib/lua/cudy/led-runtime.lua')
local count=0
local function test(name,fn) fn(); count=count+1; print('PASS '..name) end
local function init()
    files={['/tmp/sysinfo/board_name']='cudy,tr3600-v1\n',['/proc/uptime']='100.00 0.0'}
    for _,name in ipairs({'white:status','red:status'}) do
        local p='/sys/class/leds/'..name..'/'
        files[p..'trigger']='[none] timer netdev'; files[p..'brightness']=name=='white:status' and '1' or '0'
    end
    writes={}; fail=nil; raw={mode='status',night='0'}; sleeps=0
end
local function led_writes()
    local n=0; for _,v in ipairs(writes) do if v[1]:find('/sys/class/leds/',1,true)==1 then n=n+1 end end; return n
end
init()
test('saving both LED states does not touch sysfs',function()
    init(); assert(R.save_leds()); assert(led_writes()==0 and files[R.dir..'/backup.json'])
end)
test('failed backup write refuses ownership',function()
    init(); fail=R.dir..'/backup.json'; assert(not R.save_leds()); assert(led_writes()==0)
end)
test('malformed existing backup refuses ownership',function()
    init(); files[R.dir..'/backup.json']=json.stringify({}); assert(not R.save_leds()); assert(led_writes()==0)
end)
test('restore returns original brightness and removes backup',function()
    init(); assert(R.save_leds()); assert(R.apply({white='off',red='on'})); assert(R.restore())
    assert(files['/sys/class/leds/white:status/brightness']=='1' and files['/sys/class/leds/red:status/brightness']=='0')
    assert(not files[R.dir..'/backup.json'])
end)
test('timer and netdev parameters saved and restored',function()
    init(); local w='/sys/class/leds/white:status/'; local r='/sys/class/leds/red:status/'
    files[w..'trigger']='none [netdev] timer'; files[w..'device_name']='eth0'; files[w..'link']='1'; files[w..'rx']='0'; files[w..'tx']='1'; files[w..'interval']='75'
    files[r..'trigger']='none [timer] netdev'; files[r..'delay_on']='123'; files[r..'delay_off']='456'
    assert(R.save_leds()); assert(R.apply({white='wait',red='slow'})); assert(R.restore())
    assert(files[w..'trigger']=='netdev' and files[w..'device_name']=='eth0' and files[w..'interval']=='75')
    assert(files[r..'trigger']=='timer' and files[r..'delay_on']=='123' and files[r..'delay_off']=='456')
end)
test('restore failure retains backup for retry',function()
    init(); assert(R.save_leds()); fail='/sys/class/leds/red:status/brightness'
    assert(not R.restore() and files[R.dir..'/backup.json']); fail=nil; assert(R.restore())
end)
test('restoring invalid backup never partially writes LEDs',function()
    init(); files[R.dir..'/backup.json']=json.stringify({['white:status']={trigger='none',brightness='1',attrs={}}})
    assert(not R.restore() and led_writes()==0)
end)
for _,flag in ipairs({'suspend','stopped'}) do
    test(flag..' prevents the daemon from writing LEDs',function()
        init(); files[R.dir..'/'..flag]='1'; assert(R.apply({white='on',red='off'})); assert(led_writes()==0)
    end)
end
test('upgrade and failsafe do not restore over system signals',function()
    for _,marker in ipairs({R.dir..'/suspend','/tmp/.failsafe'}) do
        init(); assert(R.save_leds()); files[marker]='1'; writes={}; assert(R.restore()); assert(led_writes()==0)
    end
end)
test('wrong board never touches LEDs',function()
    init(); files['/tmp/sysinfo/board_name']='other,router'; assert(not R.save_leds())
    assert(R.apply({white='on',red='off'}) and R.restore()); assert(led_writes()==0)
end)
local production_snapshot=R.snapshot
local production_capture=R.capture
test('uplink identity ignores LAN and unrelated USB network interface changes',function()
    init()
    local lan,usb='UP','absent'
    local calls={}
    R.capture=function(command)
        calls[#calls+1]=command
        if command=='ip -4 route show table main default' then return 'default via 192.168.0.1 dev eth0 proto static src 192.168.0.101' end
        if command=='ip -o link show dev eth0' then return '2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP' end
        if command=='ip -o -4 addr show dev eth0 scope global' then return '2: eth0 inet 192.168.0.101/24 brd 192.168.0.255 scope global eth0 valid_lft 120 preferred_lft 120' end
        if command:find('eth1',1,true) then return lan end
        if command:find('usb0',1,true) then return usb end
        error('unexpected all-interface query: '..command)
    end
    files['/sys/class/net/eth0/operstate']='up\n'; files['/sys/class/net/eth0/carrier']='1\n'
    local before=R.uplink_data(); lan='DOWN'; usb='UP'
    assert(before==R.uplink_data())
    for _,command in ipairs(calls) do assert(not command:find('eth1',1,true) and not command:find('usb0',1,true)) end
    R.capture=production_capture
end)

test('uplink identity detects WAN link address gateway and selected exit changes',function()
    init(); local dev,address,gateway='eth0','192.168.0.101/24','192.168.0.1'
    R.capture=function(command)
        if command=='ip -4 route show table main default' then return 'default via '..gateway..' dev '..dev end
        if command=='ip -o link show dev '..dev then return '2: '..dev..': <UP,LOWER_UP> mtu 1500 state UP' end
        if command=='ip -o -4 addr show dev '..dev..' scope global' then return '2: '..dev..' inet '..address..' scope global' end
        error('unexpected query: '..command)
    end
    files['/sys/class/net/eth0/operstate']='up'; files['/sys/class/net/eth0/carrier']='1'
    local before=R.uplink_data()
    files['/sys/class/net/eth0/carrier']='0'; assert(before~=R.uplink_data()); files['/sys/class/net/eth0/carrier']='1'
    address='192.168.0.102/24'; assert(before~=R.uplink_data()); address='192.168.0.101/24'
    gateway='192.168.0.2'; assert(before~=R.uplink_data()); gateway='192.168.0.1'
    dev='pppoe-wan'; address='114.246.103.22/32'; assert(before~=R.uplink_data())
    R.capture=production_capture
end)

test('uplink identity ignores address lease timers',function()
    init(); local lifetime='120'
    R.capture=function(command)
        if command=='ip -4 route show table main default' then return 'default dev pppoe-wan' end
        if command=='ip -o link show dev pppoe-wan' then return '8: pppoe-wan: <POINTOPOINT,UP,LOWER_UP> mtu 1492 state UNKNOWN' end
        if command=='ip -o -4 addr show dev pppoe-wan scope global' then return '8: pppoe-wan inet 114.246.103.22/32 scope global valid_lft '..lifetime..' preferred_lft '..lifetime end
        error('unexpected query: '..command)
    end
    local before=R.uplink_data(); lifetime='60'; assert(before==R.uplink_data())
    R.capture=production_capture
end)

test('uplink identity tracks all default exits and detects missing route',function()
    init(); local routes='default dev eth0 metric 10\ndefault dev usb0 metric 20'
    local usb='UP,LOWER_UP'
    R.capture=function(command)
        if command=='ip -4 route show table main default' then return routes end
        if command=='ip -o link show dev eth0' then return '2: eth0: <UP,LOWER_UP>' end
        if command=='ip -o link show dev usb0' then return '9: usb0: <'..usb..'>' end
        if command=='ip -o -4 addr show dev eth0 scope global' then return '2: eth0 inet 192.168.0.101/24 scope global' end
        if command=='ip -o -4 addr show dev usb0 scope global' then return '9: usb0 inet 10.0.0.2/24 scope global' end
        error('unexpected query: '..command)
    end
    local before=R.uplink_data(); usb='UP'; assert(before~=R.uplink_data())
    routes=''; assert(before~=R.uplink_data())
    R.capture=production_capture
end)

test('untrusted exit interface names cannot become shell commands',function()
    init(); local calls=0
    R.capture=function(command)
        calls=calls+1; assert(command=='ip -4 route show table main default')
        return 'default dev eth0;touch_BAD'
    end
    assert(R.uplink_data():find('invalid%-device')); assert(calls==1)
    R.capture=production_capture
end)

local state={}
R.snapshot=function() return state end
local function observed()
    init(); state={id='id-A',now=100,uplink=0,busy=false,mode='global',ready=true}
    return assert(R.begin())
end
test('proxy publication binds identity and monotonic timestamp',function()
    local token=observed(); state.now=105; assert(R.finish(token,true))
    local p=R.read(R.dir..'/proxy.json'); assert(p.id=='id-A' and p.at==105 and p.result==true and p.key==token.key)
end)
test('in-flight node/config/uplink change rejects proxy sample',function()
    local token=observed(); state.id='id-B'; assert(not R.finish(token,true)); assert(not files[R.dir..'/proxy.json'])
end)
test('busy, expired, future and suspended observations rejected',function()
    for _,variant in ipairs({'busy','expired','future','suspend'}) do
        local token=observed()
        if variant=='busy' then state.busy=true elseif variant=='expired' then state.now=131 elseif variant=='future' then state.now=99 else files[R.dir..'/suspend']='1' end
        assert(not R.finish(token,false)); assert(not files[R.dir..'/proxy.json'])
    end
end)
test('direct/off/default modes do not publish proxy observations',function()
    observed(); state.mode='direct'; assert(not R.begin())
    state.mode='global'; raw.mode='off'; assert(not R.begin()); raw.mode='default'; assert(not R.begin())
end)
test('direct probe uses bounded HEAD, direct routing and valid TLS',function()
    init(); state={id='direct-id',now=100,uplink=0,busy=false,mode='direct'}
    R.capture=function(command)
        assert(command:find("--noproxy '*'",1,true) and command:find('--head',1,true) and command:find('--max-time 5',1,true))
        assert(not command:find('--insecure',1,true)); return '200 OK'
    end
    assert(R.direct(state).result==true)
end)
test('HTTP code without successful curl exit is failure',function()
    R.capture=function() return '200' end; assert(R.direct(state).result==false)
end)
test('direct redirect counts as reachable and changes invalidate result',function()
    R.capture=function() return '302 OK' end; assert(R.direct(state).result==true)
    local before={id='old',mode='direct',busy=false,uplink=0}; assert(not R.direct(before))
end)
test('wait/slow LED timer durations are explicit',function()
    init(); assert(R.apply({white='wait',red='slow'}))
    assert(files['/sys/class/leds/white:status/delay_on']=='500' and files['/sys/class/leds/white:status/delay_off']=='1500')
    assert(files['/sys/class/leds/red:status/delay_on']=='1000' and files['/sys/class/leds/red:status/delay_off']=='1000')
end)
test('Lua 5.1 wait status decodes uplink 1 as offline and 2 as unknown',function()
    init(); R.snapshot=production_snapshot
    R.capture=function(command) if command:find('main.mode',1,true) then return 'global' end; return string.rep('a',64)..'  -' end
    files['/var/etc/mango/runtime-state']='global\nnode\n'
    for rc,want in pairs({[0]=0,[256]=1,[512]=2}) do
        os.execute=function(command) if command:find('mango-uplink',1,true) then return rc end; return 0 end
        assert(R.snapshot().uplink==want)
    end
    os.execute=real_execute
end)
test('daemon default mode does not acquire LEDs',function()
    init(); raw.mode='default'; R.run(); assert(led_writes()==0)
end)
test('daily-off run exits on stop and can restore original lights',function()
    init(); raw.mode='off'; R.snapshot=function() return {id='off-id',now=100,mode='global',board='cudy,tr3600-v1'} end
    R.run(); assert(files['/sys/class/leds/white:status/brightness']=='0')
    assert(R.restore()); assert(files['/sys/class/leds/white:status/brightness']=='1')
end)
R.snapshot=production_snapshot; R.capture=production_capture; os.execute=real_execute
print('LED runtime/probe/backup/restore/priority: '..count..' tests passed')
