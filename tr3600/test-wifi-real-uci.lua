-- Use libuci with an isolated config directory supplied by the test runner.
local engine=dofile(arg[1])
local u=require('uci').cursor(arg[2],arg[2]..'/delta')
local function copy(v)
    if type(v)~='table' then return v end
    local out={}; for k,x in pairs(v) do out[k]=copy(x) end; return out
end
local function equal(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~='table' then return a==b end
    for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end
    return true
end
local original=u:get_all('wireless')
local steering=u:get_all('usteer')
local backup,commands
commands=0
local e={
    board=function() return 'cudy,tr3600-v1' end,
    available=function() return true end,
    load=function() return copy(backup) end,
    save=function(b) backup=copy(b); return true end,
    erase=function() backup=nil; return true end,
    run=function() commands=commands+1; return true end
}
assert(engine.apply(u,e,false))
assert(u:get('wireless','ap2','ssid')=='Unified-Test')
assert(u:get('wireless','ap2','key')=='OldPass_5G')
assert(u:get('usteer','main','ssid_list')[1]=='Unified-Test')
assert(u:set('cudy_wifi','main','enabled','0'))
assert(u:commit('cudy_wifi'))
assert(engine.apply(u,e,false))
assert(equal(original,u:get_all('wireless')))
assert(equal(steering,u:get_all('usteer')))
assert(not backup and commands==4)
print('Actual libuci isolated directory: commit, lists, absent fields and full restoration passed')
