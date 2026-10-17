local module=assert(loadfile(arg[1]))()
local function copy(v)local o={};for k,x in pairs(v)do o[k]=type(x)=='table' and copy(x)or x end;return o end
local function equal(a,b)
    if type(a)~=type(b)then return false end
    if type(a)~='table'then return a==b end
    for k,v in pairs(a)do if not equal(v,b[k])then return false end end
    for k in pairs(b)do if a[k]==nil then return false end end
    return true
end
local base={['.name']='fixture',service_name='dynu.com',enabled='1',use_ipv6='0',
    domain='fixture.example.net',lookup_host='fixture.example.net',
    username='synthetic-user',password='synthetic-only',ip_source='network',ip_network='wan'}
local function cursor(v)
    local u={data=copy(v),commits=0}
    function u:foreach(_,kind,fn)for _,s in pairs(self.data)do if s['.name']then fn(copy(s))end end end
    function u:get(_,name,key)if key then return self.data[name]and self.data[name][key]end;return self.data[name]and'ddns'end
    function u:section(_,_,name,values)self.data[name]=copy(values);return name end
    function u:set(_,name,key,value)assert(self.data[name]);self.data[name][key]=value;return true end
    function u:commit(_)self.commits=self.commits+1;return true end
    return u
end
local count=0
local function ok(name,fn)fn();count=count+1;print('PASS migration: '..name)end
for _,enabled in ipairs({'0','1'})do
    ok('preserve credentials/domain/enable '..enabled,function()
        local s=copy(base);s.enabled=enabled;local u=cursor({fixture=s})
        assert(module.apply(u)==1 and u.commits==1)
        local a=u.data.fixture
        for _,k in ipairs({'username','password','domain','lookup_host','enabled'})do assert(a[k]==s[k],k)end
        assert(a.use_https=='1'and a.service_name=='cudy-dynu-https'and a.ip_source=='web')
        assert(a.ip_url=='https://ipv4.icanhazip.com'and a.bind_network=='wan')
        local saved=copy(u.data);assert(module.apply(u)==0 and u.commits==1 and equal(saved,u.data))
    end)
end
for _,variant in ipairs({'ipv6','other','custom-script','custom-url','already-migrated'})do
    ok('skip '..variant,function()
        local s=copy(base)
        if variant=='ipv6'then s.use_ipv6='1'elseif variant=='other'then s.service_name='other.example'
        elseif variant=='custom-script'then s.update_script='/etc/custom-fixture'
        elseif variant=='custom-url'then s.update_url='https://custom.example/'
        else s.service_name='cudy-dynu-https';s.cudy_https_revision='1';s.check_interval='25'end
        local u=cursor({fixture=s});local before=copy(u.data)
        assert(module.apply(u)==0 and u.commits==0 and equal(before,u.data))
    end)
end
ok('fresh device has no personal profile',function()local u=cursor({global={}});assert(module.apply(u)==0 and u.commits==0)end)
ok('migrate existing hotfix profile once',function()
    local s=copy(base);s.service_name='cudy-dynu-https';local u=cursor({fixture=s})
    assert(module.apply(u)==1 and module.apply(u)==0)
end)
print('PASS all'..count..' Dynu migration regressions')
