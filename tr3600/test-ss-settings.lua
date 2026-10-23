local M=dofile(assert(arg[1], 'Pass the ss-zt.lua module path'))
local passed=0
local function test(name,fn)
    local ok,err=pcall(fn)
    assert(ok,name..': '..tostring(err))
    passed=passed+1
end
local function copy(value)
    if type(value)~='table' then return value end
    local result={}; for key,item in pairs(value) do result[key]=copy(item) end
    return result
end
local raw={enabled='1',listen='192.168.77.6',subnet='192.168.77.0/24',interface='ztfixture123',
    network_id='0011223344556677',port='8388',method='aes-128-gcm',password=string.rep('F',24)}
local request={enabled=true,port=8388,method='aes-128-gcm',password=''}
local function reject(input,config)
    local ok=pcall(M.request,config or raw,input)
    assert(not ok,'request unexpectedly accepted invalid settings')
end
local function inbound(c)
    return {tag=M.tag,listen=c.listen,port=c.port,protocol='shadowsocks',
        settings={method=c.method,password=c.password,network='tcp,udp'}}
end

test('typed request preserves empty password and private scope',function()
    local result=M.request(raw,request)
    assert(result.password==raw.password)
    assert(result.listen==raw.listen and result.subnet==raw.subnet and result.interface==raw.interface and result.network_id==raw.network_id)
    assert(result.enabled=='1' and result.port=='8388')
    assert(raw.port=='8388' and raw.password==string.rep('F',24),'raw settings mutated')
end)
test('strong new settings and disabled state',function()
    local result=M.request(raw,{enabled=false,port=8389,method='chacha20-ietf-poly1305',password=string.rep('N',128)})
    assert(result.enabled=='0' and result.port=='8389' and result.method=='chacha20-ietf-poly1305' and result.password==string.rep('N',128))
    assert(raw.enabled=='1' and raw.method=='aes-128-gcm' and raw.password==string.rep('F',24))
end)
test('request requires exact typed fields',function()
    for key,values in pairs({enabled={'1',1},port={'8388',false},method={128,false},password={24,false}}) do
        for _,value in ipairs(values) do local r=copy(request); r[key]=value; reject(r) end
        local r=copy(request); r[key]=nil; reject(r)
    end
    reject(nil); reject('settings'); reject({})
end)
test('request refuses all scope and unknown keys',function()
    for _,key in ipairs({'listen','subnet','interface','network_id','enabled_extra','uri','password_set'}) do
        local r=copy(request); r[key]='injected'; reject(r)
    end
end)
test('request checks strong key even before disable',function()
    for _,password in ipairs({string.rep('A',23),string.rep('A',129),string.rep('A',24)..'\n',string.rep('A',24)..string.char(127)}) do
        local r=copy(request); r.password=password; reject(r)
    end
    local missing=copy(raw); missing.password=nil; reject(request,missing)
    local disabled=copy(request); disabled.enabled=false; disabled.password='weak'; reject(disabled)
end)
test('request rejects unencrypted cipher and reserved or fractional ports',function()
    for _,method in ipairs({'none','plain','rc4-md5','AES-128-GCM'}) do local r=copy(request); r.method=method; reject(r) end
    for _,port in ipairs({1023,65536,1053,10808,10809,10810,12345,8388.5}) do local r=copy(request); r.port=port; reject(r) end
end)
test('request follows UTF-8 byte boundaries',function()
    local cjk=string.char(0xe4,0xb8,0xad)
    local emoji=string.char(0xf0,0x9f,0x94,0x91)
    local r=copy(request); r.password=string.rep(cjk,8); assert(#M.request(raw,r).password==24)
    r.password=string.rep(cjk,43); reject(r)
    r.password=string.rep(emoji,6); assert(#M.request(raw,r).password==24)
    r.password=string.rep(emoji,33); reject(r)
end)
test('matches accepts exact inbound and unrelated listeners',function()
    local c=M.validate(raw)
    assert(M.matches({inbounds={{tag='existing',protocol='socks'},inbound(c)}},c,true))
end)
test('matches rejects wrong method or password',function()
    local c=M.validate(raw)
    local v=inbound(c); v.settings.method='aes-256-gcm'; assert(not M.matches({inbounds={v}},c,true))
    v=inbound(c); v.settings.password=string.rep('W',24); assert(not M.matches({inbounds={v}},c,true))
end)
test('matches requires both TCP and UDP',function()
    local c=M.validate(raw)
    for _,network in ipairs({'tcp','udp','udp,tcp','tcp,udp,unix'}) do
        local v=inbound(c); v.settings.network=network; assert(not M.matches({inbounds={v}},c,true))
    end
end)
test('matches rejects duplicate service tags',function()
    local c=M.validate(raw)
    assert(not M.matches({inbounds={inbound(c),inbound(c)}},c,true))
    assert(not M.matches({inbounds={inbound(c),inbound(c)}},c,false))
end)
test('matches rejects wrong listener identity',function()
    local c=M.validate(raw)
    for key,value in pairs({listen='0.0.0.0',port=8389,protocol='socks'}) do
        local v=inbound(c); v[key]=value; assert(not M.matches({inbounds={v}},c,true))
    end
    assert(not M.matches({inbounds={}},c,true))
    assert(not M.matches({inbounds={inbound(c)}},nil,true))
end)
test('offline or disabled state matches only absent inbound',function()
    local c=M.validate(raw)
    assert(M.matches({inbounds={{tag='existing'}}},c,false))
    assert(M.matches({inbounds={}},nil,false))
    assert(M.matches(nil,nil,false))
    assert(not M.matches({inbounds={inbound(c)}},c,false))
end)
print('PASS '..passed..' SS settings and complete readiness-match regressions')
