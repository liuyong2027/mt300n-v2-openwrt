-- Pure fixtures: this test never loads UCI or reads router configuration.
local engine = dofile(arg[1] or 'tr3600/luci-app-cudy-wifi/root/usr/lib/lua/cudy/wifi.lua')
local count = 0
local function copy(v)
    if type(v) ~= 'table' then return v end
    local out={}; for k,x in pairs(v) do out[k]=copy(x) end; return out
end
local function equal(a,b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= 'table' then return a == b end
    for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
    for k in pairs(b) do if a[k] == nil then return false end end
    return true
end
local function fixture()
    local d = {
        cudy_wifi={main={['.type']='wifi',enabled='1',steering='1',ssid='Unified-Test',key='TestPass_1234',encryption='sae-mixed'}},
        wireless={
            r2={['.type']='wifi-device',band='2g',disabled='0',channel='1',htmode='HT20'},
            r5={['.type']='wifi-device',band='5g',disabled='0',channel='36',htmode='HE80'},
            ap2={['.type']='wifi-iface',device='r2',mode='ap',network='lan',ssid='Separate-2G',key='OldPass_2G',encryption='psk2'},
            ap5={['.type']='wifi-iface',device='r5',mode='ap',network={'lan'},ssid='Separate-5G',key='OldPass_5G',encryption='sae-mixed',ieee80211w='1'},
            guest={['.type']='wifi-iface',device='r5',mode='ap',network='guest',ssid='Guest',key='GuestPass_123',encryption='psk2'},
            uplink={['.type']='wifi-iface',device='r2',mode='sta',network='wwan',ssid='Upstream',key='UpstreamPass',encryption='psk2'}},
        usteer={main={['.type']='usteer',network='lan',enabled='0',local_mode='0',ssid_list={'OldScope'}}}
    }
    local original=copy(d)
    local u={}
    function u:get_all(config,section) return copy(d[config] and d[config][section]) end
    function u:get(config,section,option)
        local s=d[config] and d[config][section]
        if not s then return end
        if option then return s[option] end
        return s['.type']
    end
    function u:foreach(config,kind,callback)
        for name,s in pairs(d[config] or {}) do
            if s['.type']==kind then local v=copy(s); v['.name']=name; callback(v) end
        end
    end
    function u:set(config,section,option,value) d[config][section][option]=copy(value); return true end
    function u:delete(config,section,option) d[config][section][option]=nil; return true end
    function u:commit(config)
        if u.fail_commit == config then u.fail_commit=nil; return false end
        return true
    end
    local e={commands={},saves=0}
    function e.board() return e.wrong_board and 'other,router' or 'cudy,tr3600-v1' end
    function e.available() return not e.missing end
    function e.load() return copy(e.backup),e.bad_file end
    function e.save(b)
        if e.fail_save then return false end
        e.backup=copy(b); e.saves=e.saves+1; return true
    end
    function e.erase()
        if e.fail_erase then return false end
        e.backup=nil; return true
    end
    function e.run(command)
        assert(command == '/sbin/wifi reload' or command == '/etc/init.d/usteer restart')
        e.commands[#e.commands+1]=command
        if e.fail_command == command then e.fail_command=nil; return false end
        return true
    end
    return d,u,e,original
end
local function test(name,fn) fn(); count=count+1; print('PASS '..name) end
local function fail_unchanged(d,u,e)
    local before=copy(d)
    local ok,message=engine.apply(u,e,false)
    assert(not ok and type(message)=='string')
    assert(equal(d,before)); assert(e.saves==0 and #e.commands==0)
    assert(not message:find('TestPass_1234',1,true))
end

test('default disabled does not touch even a manually configured steering service',function()
    local d,u,e=fixture(); d.cudy_wifi.main.enabled='0'; d.usteer.main.enabled='1'
    local before=copy(d); assert(engine.apply(u,e,false)); assert(equal(d,before)); assert(e.saves==0 and #e.commands==0)
end)
test('enable syncs credentials/security/k-v and scopes steering to local selected SSID',function()
    local d,u,e,original=fixture(); assert(engine.apply(u,e,false)); assert(e.backup and e.saves==1)
    assert(d.wireless.ap2.ssid == d.wireless.ap5.ssid and d.wireless.ap2.key == d.wireless.ap5.key)
    assert(d.wireless.ap2.encryption=='sae-mixed' and d.wireless.ap2.ieee80211w=='1')
    assert(d.wireless.ap2.ieee80211k=='1' and d.wireless.ap5.bss_transition=='1')
    assert(d.usteer.main.enabled=='1' and d.usteer.main.local_mode=='1')
    assert(equal(d.usteer.main.ssid_list,{'Unified-Test'}) and d.usteer.main.band_steering_interval=='30000')
    assert(equal(d.wireless.r2,original.wireless.r2) and equal(d.wireless.r5,original.wireless.r5))
    assert(equal(d.wireless.guest,original.wireless.guest) and equal(d.wireless.uplink,original.wireless.uplink))
end)
test('disable restores names/keys/security/lists and absent options exactly',function()
    local d,u,e,original=fixture(); assert(engine.apply(u,e,false)); d.cudy_wifi.main.enabled='0'
    assert(engine.apply(u,e,false)); assert(equal(d.wireless,original.wireless) and equal(d.usteer,original.usteer)); assert(not e.backup)
end)
test('reapply and reboot preserve first snapshot; updated unified credentials still restore original',function()
    local d,u,e,original=fixture(); assert(engine.apply(u,e,false)); local first=copy(e.backup)
    d.cudy_wifi.main.ssid='Changed'; assert(engine.apply(u,e,true)); assert(equal(e.backup,first) and e.saves==1)
    assert(#e.commands==2); d.cudy_wifi.main.enabled='0'; assert(engine.apply(u,e,true))
    assert(equal(d.wireless,original.wireless) and #e.commands==2)
end)
test('steering can be disabled independently; Wi-Fi remains unified',function()
    local d,u,e=fixture(); d.cudy_wifi.main.steering='0'; assert(engine.apply(u,e,false))
    assert(d.wireless.ap2.ssid==d.wireless.ap5.ssid and d.usteer.main.enabled=='0' and d.wireless.ap5.bss_transition=='0')
end)
test('blank common password reuses valid selected 5 GHz key without exposing it',function()
    local d,u,e=fixture(); d.cudy_wifi.main.key=''; local ok,message=engine.apply(u,e,false)
    assert(ok and d.wireless.ap2.key=='OldPass_5G' and not message:find('OldPass_5G',1,true))
end)
test('printable quotes/backslashes remain data, never interpolated into commands',function()
    local d,u,e=fixture(); d.cudy_wifi.main.key='Test"Pass\\123'; assert(engine.apply(u,e,false)); assert(d.wireless.ap5.key==d.cudy_wifi.main.key)
end)
for _,mode in ipairs({'psk2','sae'}) do
    test('security '..mode,function()
        local d,u,e=fixture(); d.cudy_wifi.main.encryption=mode; assert(engine.apply(u,e,false))
        assert(d.wireless.ap2.ieee80211w == (mode=='sae' and '2' or '0'))
    end)
end
for _,case in ipairs({
    {'wrong device',function(d,u,e) e.wrong_board=true end},
    {'missing components',function(d,u,e) e.missing=true end},
    {'short password',function(d) d.cudy_wifi.main.key='short' end},
    {'64 character password',function(d) d.cudy_wifi.main.key=string.rep('x',64) end},
    {'password newline',function(d) d.cudy_wifi.main.key='Test\nPass123' end},
    {'invalid fallback password',function(d) d.cudy_wifi.main.key=''; d.wireless.ap5.key='short' end},
    {'empty SSID',function(d) d.cudy_wifi.main.ssid='' end},
    {'overlong UTF-8 SSID',function(d) d.cudy_wifi.main.ssid=string.rep('中文',6) end},
    {'SSID control character',function(d) d.cudy_wifi.main.ssid='Bad\nSSID' end},
    {'open security prohibited',function(d) d.cudy_wifi.main.encryption='none' end},
    {'radio disabled',function(d) d.wireless.r5.disabled='1' end},
    {'AP disabled',function(d) d.wireless.ap2.disabled='1' end},
    {'guest AP rejected',function(d) d.cudy_wifi.main.ap5g='guest' end},
    {'guest SSID collision rejected',function(d) d.wireless.guest.ssid='Unified-Test' end},
    {'STA rejected',function(d) d.cudy_wifi.main.ap2g='uplink' end},
    {'same AP rejected',function(d) d.cudy_wifi.main.ap5g='ap2' end},
    {'ambiguous APs require selection',function(d) d.wireless.second=copy(d.wireless.ap2) end},
    {'multiple steering sections rejected',function(d) d.usteer.extra=copy(d.usteer.main) end},
    {'unreadable backup',function(d,u,e) e.bad_file=true end},
    {'invalid backup',function(d,u,e) e.backup={version=99} end},
    {'backup save fails closed',function(d,u,e) e.fail_save=true end}
}) do test(case[1],function() local d,u,e=fixture(); case[2](d,u,e); fail_unchanged(d,u,e) end) end
test('explicit AP selection supports multiple LAN APs without modifying unselected AP',function()
    local d,u,e=fixture(); d.wireless.second=copy(d.wireless.ap2); d.cudy_wifi.main.ap2g='ap2'; d.cudy_wifi.main.ap5g='ap5'
    local second=copy(d.wireless.second); assert(engine.apply(u,e,false)); assert(equal(second,d.wireless.second))
end)
for _,command in ipairs({'/sbin/wifi reload','/etc/init.d/usteer restart'}) do
    test('rollback after '..command..' failure',function()
        local d,u,e,original=fixture(); e.fail_command=command; assert(not engine.apply(u,e,false))
        assert(equal(d.wireless,original.wireless) and equal(d.usteer,original.usteer)); assert(not e.backup)
    end)
end
test('rollback after second config commit failure',function()
    local d,u,e,original=fixture(); u.fail_commit='usteer'; assert(not engine.apply(u,e,false))
    assert(equal(d.wireless,original.wireless) and equal(d.usteer,original.usteer)); assert(not e.backup)
end)
test('disable reload failure retains original snapshot and restores merged state for retry',function()
    local d,u,e=fixture(); assert(engine.apply(u,e,false)); local live=copy(d.wireless)
    d.cudy_wifi.main.enabled='0'; e.fail_command='/sbin/wifi reload'; assert(not engine.apply(u,e,false))
    assert(equal(d.wireless,live) and e.backup); assert(engine.apply(u,e,false)); assert(not e.backup)
end)
test('removed AP fails closed rather than partially restoring another interface',function()
    local d,u,e=fixture(); assert(engine.apply(u,e,false)); d.cudy_wifi.main.enabled='0'; d.wireless.ap5=nil
    local before=copy(d); assert(not engine.apply(u,e,false)); assert(equal(before,d) and e.backup)
end)
test('backup cleanup failure allows safe retry',function()
    local d,u,e,original=fixture(); assert(engine.apply(u,e,false)); d.cudy_wifi.main.enabled='0'; e.fail_erase=true
    assert(not engine.apply(u,e,false)); assert(equal(d.wireless,original.wireless) and e.backup)
    e.fail_erase=false; assert(engine.apply(u,e,false)); assert(not e.backup)
end)
print('Wi-Fi configuration/restore/isolation/rollback: '..count..' tests passed')
