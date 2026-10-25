-- Native UCI/nixio only. Arguments: migration module, config module, fresh /tmp directory, validator module.
local migrate_path,config_path,root=arg[1],arg[2],arg[3]
assert(type(root)=='string' and root:match('^/tmp/[A-Za-z0-9][A-Za-z0-9._/-]*$') and
    not root:find('//',1,true) and root:sub(-1)~='/','Fresh /tmp sandbox required')
for part in root:gmatch('[^/]+') do assert(part~='.' and part~='..','Unsafe sandbox path') end
local fs=require('nixio.fs')
local uci=require('uci')
assert(not fs.lstat(root),'Sandbox already exists')
local ancestor=''
for part in root:match('^(.*)/[^/]+$'):gmatch('[^/]+') do
    ancestor=ancestor..'/'..part
    assert((fs.lstat(ancestor) or {}).type=='dir','Sandbox ancestor must be a real directory')
end
local migration=assert(dofile(migrate_path))
local config=assert(dofile(config_path))
-- The generated validator loads this exact module once at its final bridge.
-- A temporary native fixture must not load a different installed/live copy.
local original_dofile=dofile
dofile=function(path)
    if path=='/usr/lib/cudy-ss/config.lua' then return config end
    return original_dofile(path)
end
local validator=assert(dofile(arg[4] or '/usr/lib/cudy-ss/ss-zt.lua'))
dofile=original_dofile
local function mkdir(path) assert(fs.mkdir(path));assert(fs.chmod(path,'700')) end
local function write(path,data) assert(fs.writefile(path,data));assert(fs.chmod(path,'600')) end
mkdir(root)
local cases={{name='disabled_preserved',enabled='0',global='0'},
    {name='enabled_global_off',enabled='1',global='0'},
    {name='enabled_global_on',enabled='1',global='1'},
    {name='fresh_disabled',enabled='0',global='0',fresh=true}}
for _,case in ipairs(cases) do
    local dir=root..'/'..case.name
    mkdir(dir);mkdir(dir..'/config');mkdir(dir..'/saved')
    local legacy="config server 'main'\n option enabled '"..case.enabled.."'\n"..[[
 option port '8386'
 option method 'aes-256-gcm'
]]
    if not case.fresh then legacy=legacy..[[
 option password 'synthetic-private-existing-password'
 option listen '10.42.0.2'
 option subnet '10.42.0.0/24'
 option interface 'ztabcdef'
 option network_id '0123456789abcdef'
]] end
    write(dir..'/config/cudy_ss',legacy)
    write(dir..'/config/shadowsocksr',"config server_global 'server_global'\n option enable_server '"..case.global.."'\n"..[[
config global 'global'
 option global_server 'owner_node'
 option run_mode 'gfw'
config servers 'owner_node'
 option server 'relay.example'
 option password 'synthetic-existing-upstream-password'
]])
    local function mapped(path)
        if path=='/etc/config/cudy_ss' then return dir..'/config/cudy_ss' end
        if path=='/etc/cudy-ssrplus' then return dir..'/state' end
        local name=path:match('^/etc/cudy%-ssrplus/([%w._-]+)$')
        assert(name,'Unexpected migration filesystem path')
        return dir..'/state/'..name
    end
    local sandbox_fs={}
    for _,name in ipairs({'access','mkdir','chmod','readfile','writefile'}) do
        local operation=name
        sandbox_fs[name]=function(path,...) return fs[operation](mapped(path),...) end
    end
    local function cursor() return assert(uci.cursor(dir..'/config',dir..'/saved')) end
    local c=cursor()
    assert(c.get_first==nil and c.section==nil,'Use native UCI without convenience helpers')
    assert(migration.run(c,sandbox_fs))
    c:close();c=cursor()
    local row=assert(c:get_all('shadowsocksr','cudy_zt_private'))
    assert(row['.type']=='server_config' and row.type=='shadowsocks')
    assert(row.cudy_private=='1' and row.cudy_access=='zerotier')
    assert(row.enable==case.enabled and row.server_port=='8386')
    assert(row.ss_method=='aes-256-gcm')
    assert(row.ss_network=='tcp,udp')
    if case.fresh then
        for _,field in ipairs({'ss_password','cudy_zt_network_id','cudy_zt_interface','cudy_zt_listen','cudy_zt_subnet'}) do
            assert(row[field]==nil,'Fresh disabled row was configured or approved automatically: '..field)
        end
    else
        assert(row.ss_password=='synthetic-private-existing-password')
        assert(row.cudy_zt_network_id=='0123456789abcdef' and row.cudy_zt_interface=='ztabcdef')
        assert(row.cudy_zt_listen=='10.42.0.2' and row.cudy_zt_subnet=='10.42.0.0/24')
    end
    assert(c:get('shadowsocksr','server_global','enable_server')==case.global)
    assert(c:get('shadowsocksr','global','global_server')=='owner_node')
    assert(c:get('shadowsocksr','global','run_mode')=='gfw')
    local raw=config.raw(c)
    assert(raw.enabled==((case.enabled=='1' and case.global=='1') and '1' or '0'))
    assert(raw.port=='8386' and raw.password==row.ss_password and raw.subnet==row.cudy_zt_subnet)
    if not case.fresh then for _,network in ipairs({'tcp','udp','tcp,udp'}) do
        assert(c:set('shadowsocksr','cudy_zt_private','ss_network',network))
        local selected=config.raw(c)
        assert(selected.network==network)
        -- Exercise validation without changing the fixture's preserved global/row switches.
        selected.enabled='1'
        local active=assert(config.validate(selected,validator.validate))
        assert(active.network==network)
        local generated=config.config(active)
        assert(generated.inbounds[1].settings.network==network and config.matches(generated,active,true))
        local rules=config.guard(active)
        local protocol=network=='tcp,udp' and '{ tcp, udp }' or network
        assert(rules:find('meta l4proto '..protocol..' th dport 8386 iifname "ztabcdef" ip saddr 10.42.0.0/24 dnat',1,true))
        assert(rules:find('ip daddr 198.18.255.2 iifname "ztabcdef" ip saddr 10.42.0.0/24 meta l4proto '..protocol..' th dport 8386 return',1,true))
        if network~='tcp,udp' then
            local denied=network=='tcp' and 'udp' or 'tcp'
            assert(rules:find('ip daddr 10.42.0.2 meta l4proto '..denied..' th dport 8386 counter drop',1,true))
        end
        generated.inbounds[1].settings.network=network=='tcp' and 'udp' or 'tcp'
        assert(not config.matches(generated,active,true),'Transport drift was accepted')
    end end
    for _,invalid in ipairs({'udp,tcp','tcp,udp,icmp','all',''}) do
        assert(c:set('shadowsocksr','cudy_zt_private','ss_network',invalid))
        assert(not pcall(config.raw,c),'Invalid transport was accepted')
    end
    assert(c:set('shadowsocksr','cudy_zt_private','ss_network','tcp,udp'))
    assert(fs.readfile(dir..'/config/cudy_ss')==legacy,'Legacy backup source changed')
    assert(fs.readfile(dir..'/state/cudy_ss.before-server-v2')==legacy)
    assert(fs.lstat(dir..'/state/cudy_ss.before-server-v2').modestr=='rw-------')
    assert(fs.lstat(dir..'/state/ss-server-v2.done').modestr=='rw-------')
    -- Retry after commit but before marker creation must respect later edits.
    assert(c:set('shadowsocksr','cudy_zt_private','server_port','9443'))
    assert(c:set('shadowsocksr','cudy_zt_private','ss_password','synthetic-owner-edited-password'))
    assert(c:commit('shadowsocksr'));c:close()
    assert(fs.remove(dir..'/state/ss-server-v2.done'))
    local before=assert(fs.readfile(dir..'/config/shadowsocksr'))
    c=cursor();assert(migration.run(c,sandbox_fs));c:close()
    assert(fs.readfile(dir..'/config/shadowsocksr')==before,'Edited unified row was overwritten')
    c=cursor();assert(migration.run(c,sandbox_fs)==false);c:close()
    assert(fs.readfile(dir..'/config/shadowsocksr')==before,'Completed migration was not a no-op')
    -- Duplicate private rows must never be silently used by runtime.
    c=cursor();assert(c:set('shadowsocksr','duplicate_private','server_config'))
    assert(c:set('shadowsocksr','duplicate_private','cudy_private','1'))
    assert(not pcall(config.raw,c),'Duplicate private row was accepted');c:close()
    print('PASS '..case.name..': native UCI private-row migration and edited-row preservation')
end
print('PASS all 4 native private SS server_config migration cases; fresh disabled preserved; TCP/UDP/both and invalid transports')
