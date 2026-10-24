-- Native libuci smoke test. Run only with an uploaded candidate and a fresh
-- directory below /tmp; all configuration and state below are synthetic.
-- Usage: lua native-uci-smoke.lua /tmp/candidate-migrate.lua /tmp/uci-smoke-123
local candidate, root = arg[1], arg[2]
assert(type(candidate) == 'string' and candidate:sub(1, 1) == '/',
    'arg[1] must be an absolute candidate migrate.lua path')
assert(type(root) == 'string' and root:match('^/tmp/[A-Za-z0-9][A-Za-z0-9._/-]*$')
    and not root:find('//', 1, true) and root:sub(-1) ~= '/',
    'arg[2] must be a fresh directory below /tmp')
for component in root:gmatch('[^/]+') do
    assert(component ~= '.' and component ~= '..', 'unsafe sandbox root')
end

local native_uci = require('uci')
local native_fs = require('nixio.fs')
local original_uci = package.loaded['uci']
local original_fs = package.loaded['nixio.fs']
local candidate_stat = native_fs.stat(candidate)
assert(candidate_stat and candidate_stat.type == 'reg', 'candidate must be a regular file')
assert(not native_fs.lstat(root), 'sandbox root already exists; use a fresh name')
local ancestor = ''
for component in root:match('^(.*)/[^/]+$'):gmatch('[^/]+') do
    ancestor = ancestor .. '/' .. component
    local info = native_fs.lstat(ancestor)
    assert(info and info.type == 'dir', 'sandbox parent must exist without symlink ancestors')
end

local function mkdir(path)
    assert(native_fs.mkdir(path), 'cannot create sandbox directory')
    assert(native_fs.chmod(path, '700'), 'cannot protect sandbox directory')
end
local function write(path, content)
    assert(native_fs.writefile(path, content), 'cannot create synthetic fixture')
    assert(native_fs.chmod(path, '600'), 'cannot protect synthetic fixture')
end
local function read(path)
    local content = native_fs.readfile(path)
    assert(content ~= nil, 'cannot read synthetic fixture')
    return content
end
local function equal(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= 'table' then return a == b end
    for key, value in pairs(a) do if not equal(value, b[key]) then return false end end
    for key in pairs(b) do if a[key] == nil then return false end end
    return true
end
local function options(cursor, config, section)
    local result = {}
    for key, value in pairs(assert(cursor:get_all(config, section), 'missing synthetic section')) do
        if key:sub(1, 1) ~= '.' then result[key] = value end
    end
    return result
end
local function contains(items, value)
    if type(items) == 'string' then return items == value end
    for _, item in ipairs(items or {}) do if item == value then return true end end
    return false
end

local common = {
    mango_proxy = [[
config policy 'main'
 option mode 'global'
 option node 'primary'
 list bypass4 '198.51.100.7'
config node 'primary'
 option protocol 'vless'
 option label 'Synthetic Mango relay'
 option address 'relay.example'
 option port '443'
 option uuid '00000000-0000-4000-8000-000000000001'
 option public_key 'synthetic-public-key'
 option sni 'example.com'
]],
    dhcp = [[
config dnsmasq 'dns'
 list server '127.0.0.1#1053'
 list server '9.9.9.9'
 option filter_aaaa '0'
 option owner_setting 'keep'
]],
    firewall = [[
config include 'mango_proxy'
 option path '/usr/libexec/mango-fw'
config rule 'mango_mark'
 option name 'Synthetic retired mark'
config rule 'owner_rule'
 option target 'REJECT'
 option name 'Synthetic owner rule'
]],
    cudy_ss = [[
config service 'main'
 option enabled '1'
 option listen '10.42.0.2'
 option subnet '10.42.0.0/24'
 option interface 'ztabcdef'
 option network_id '0123456789abcdef'
 option port '8388'
 option method 'aes-256-gcm'
 option password 'synthetic-private-existing-password'
]]
}
local cases = {
    {
        name = 'seeded_nil',
        ssr = [[
config global 'global'
 option global_server 'nil'
 option run_mode 'gfw'
]],
        initialize = true
    },
    {
        name = 'missing_global_access_control',
        ssr = '# Synthetic fresh configuration with no sections.\n',
        initialize = true
    },
    {
        name = 'preserve_user_selection',
        ssr = [[
config global 'global'
 option global_server 'cfg024a8f'
 option run_mode 'gfw'
 option udp_relay_server 'custom-udp'
 option prefer_nft '0'
 option router_proxy '0'
 option default_node_local_port '4321'
 option dports '2'
 option custom_ports '80,443'
 option owner_setting 'keep'
 list owner_list 'alpha'
 list owner_list 'beta'
config servers 'cfg024a8f'
 option type 'v2ray'
 option server 'owner-relay.example'
 option password 'synthetic-owner-password'
config servers 'cfg_second'
 option server 'second-relay.example'
config access_control 'access_control'
 list Interface 'lan'
 list Interface 'guest'
 option router_proxy '0'
 list wan_bp_ips '203.0.113.7'
]],
        initialize = false
    }
}

-- No fake cursor helpers: cursor() returns the actual native libuci userdata.
-- The four state operations exercised by the candidate call native nixio.fs.
-- Unexpected filesystem mutations are rejected instead of touching /etc.
local forbidden_mutations = {
    mkdir = true, mkdirr = true, rmdir = true, rename = true, move = true,
    copy = true, link = true, symlink = true, chown = true, utimes = true
}
local function execute_in_fixture(fixture)
    local prefix = '/etc/cudy-ssrplus/'
    local function mapped(path, mutation)
        if type(path) == 'string' and path:sub(1, #prefix) == prefix then
            local name = path:sub(#prefix + 1)
            assert(name:match('^[A-Za-z0-9][A-Za-z0-9._-]*$'), 'unsafe state filename')
            return fixture.state .. '/' .. name
        end
        assert(not mutation, 'candidate attempted filesystem write outside synthetic state')
        return path
    end
    local fs = setmetatable({
        access = function(path, ...) return native_fs.access(mapped(path, false), ...) end,
        readfile = function(path, ...) return native_fs.readfile(mapped(path, false), ...) end,
        stat = function(path, ...) return native_fs.stat(mapped(path, false), ...) end,
        lstat = function(path, ...) return native_fs.lstat(mapped(path, false), ...) end,
        writefile = function(path, ...)
            return native_fs.writefile(mapped(path, true), ...)
        end,
        chmod = function(path, ...)
            fixture.chmod_calls = fixture.chmod_calls + 1
            return native_fs.chmod(mapped(path, true), ...)
        end,
        remove = function(path, ...)
            return native_fs.remove(mapped(path, true), ...)
        end
    }, { __index = function(_, key)
        assert(not forbidden_mutations[key], 'candidate requested unexpected filesystem mutation')
        return native_fs[key]
    end })
    package.loaded['uci'] = setmetatable({
        cursor = function(...)
            assert(select('#', ...) == 0, 'candidate changed cursor constructor arguments')
            return assert(native_uci.cursor(fixture.confdir, fixture.savedir))
        end
    }, { __index = native_uci })
    package.loaded['nixio.fs'] = fs
    local ok, failure = xpcall(function() dofile(candidate) end, debug.traceback)
    package.loaded['uci'] = original_uci
    package.loaded['nixio.fs'] = original_fs
    collectgarbage('collect')
    assert(ok, failure)
end

local function snapshot(fixture)
    local result = {}
    for _, name in ipairs({'mango_proxy', 'shadowsocksr', 'dhcp', 'firewall', 'cudy_ss'}) do
        result[name] = read(fixture.confdir .. '/' .. name)
    end
    result.done = read(fixture.state .. '/migration-v1.done')
    result.seed = native_fs.readfile(fixture.state .. '/seeded-config')
    return result
end

local function run_case(case)
    local dir = root .. '/' .. case.name
    mkdir(dir)
    local fixture = {confdir = dir .. '/config', savedir = dir .. '/saved',
        state = dir .. '/state', chmod_calls = 0}
    mkdir(fixture.confdir); mkdir(fixture.savedir); mkdir(fixture.state)
    for name, content in pairs(common) do write(fixture.confdir .. '/' .. name, content) end
    write(fixture.confdir .. '/shadowsocksr', case.ssr)
    write(fixture.state .. '/seeded-config', '1\n')
    local private_before = read(fixture.confdir .. '/cudy_ss')
    local mango_before = read(fixture.confdir .. '/mango_proxy')
    local initial = assert(native_uci.cursor(fixture.confdir, fixture.savedir))
    local globals_before, imported_before, second_before
    if not case.initialize then
        globals_before = options(initial, 'shadowsocksr', 'global')
        imported_before = options(initial, 'shadowsocksr', 'cfg024a8f')
        second_before = options(initial, 'shadowsocksr', 'cfg_second')
    end
    local owner_rule = options(initial, 'firewall', 'owner_rule')
    initial = nil
    collectgarbage('collect')
    execute_in_fixture(fixture)
    local cursor = assert(native_uci.cursor(fixture.confdir, fixture.savedir))
    assert(cursor:get('shadowsocksr', 'global') == 'global', 'global section was not created/preserved')
    assert(cursor:get('shadowsocksr', 'access_control') == 'access_control', 'access_control section missing')
    assert(cursor:get('shadowsocksr', 'migrated_primary') == 'servers', 'Mango node was not migrated')
    assert(cursor:get('shadowsocksr', 'migrated_primary', 'server') == 'relay.example', 'node address migration failed')
    assert(cursor:get('shadowsocksr', 'migrated_primary', 'v2ray_protocol') == 'vless', 'node protocol migration failed')
    assert(cursor:get('shadowsocksr', 'migrated_primary', 'reality') == '1', 'node Reality migration failed')
    assert(cursor:get('shadowsocksr', 'migrated_primary', 'vmess_id') == common.mango_proxy:match("option uuid '([^']+)'"),
        'node identity migration failed')
    if case.initialize then
        assert(cursor:get('shadowsocksr', 'global', 'global_server') == 'migrated_primary', 'seeded nil selection was not initialized')
        assert(cursor:get('shadowsocksr', 'global', 'run_mode') == 'all', 'Mango global mode migration failed')
        assert(cursor:get('shadowsocksr', 'global', 'udp_relay_server') == 'same', 'UDP selection migration failed')
        assert(cursor:get('shadowsocksr', 'global', 'router_proxy') == '1', 'router proxy migration failed')
        assert(cursor:get('dhcp', 'dns', 'filter_aaaa') == '1', 'initial IPv6 DNS policy migration failed')
        assert(contains(cursor:get('shadowsocksr', 'access_control', 'wan_bp_ips'), '198.51.100.7'), 'old bypass was not imported')
    else
        assert(equal(options(cursor, 'shadowsocksr', 'global'), globals_before), 'existing user global settings changed')
        assert(equal(options(cursor, 'shadowsocksr', 'cfg024a8f'), imported_before), 'selected user node changed')
        assert(equal(options(cursor, 'shadowsocksr', 'cfg_second'), second_before), 'second user node changed')
        assert(cursor:get('shadowsocksr', 'access_control', 'router_proxy') == '0', 'user access control changed')
        assert(cursor:get('dhcp', 'dns', 'filter_aaaa') == '0', 'user IPv6 DNS policy changed')
        assert(not contains(cursor:get('shadowsocksr', 'access_control', 'wan_bp_ips'), '198.51.100.7'), 'old bypass overwrote user policy')
    end
    local interfaces = cursor:get('shadowsocksr', 'access_control', 'Interface')
    assert(contains(interfaces, 'lan') and contains(interfaces, 'cudy_ss'), 'private SS interface missing')
    if not case.initialize then assert(contains(interfaces, 'guest'), 'existing interface was lost') end
    assert(contains(cursor:get('shadowsocksr', 'access_control', 'wan_bp_ips'), '198.18.255.0/30'), 'private SS bypass missing')
    local servers = cursor:get('dhcp', 'dns', 'server')
    assert(not contains(servers, '127.0.0.1#1053') and contains(servers, '9.9.9.9'), 'retired DNS was not removed safely')
    assert(cursor:get('dhcp', 'dns', 'owner_setting') == 'keep', 'other DNS setting changed')
    assert(not cursor:get('firewall', 'mango_proxy') and not cursor:get('firewall', 'mango_mark'), 'retired Mango firewall entries remain')
    assert(equal(options(cursor, 'firewall', 'owner_rule'), owner_rule), 'owner firewall rule changed')
    assert(read(fixture.confdir .. '/cudy_ss') == private_before, 'private SS configuration bytes changed')
    assert(read(fixture.confdir .. '/mango_proxy') == mango_before, 'Mango source configuration bytes changed')
    assert(read(fixture.state .. '/migration-v1.done') == '1\n', 'completion marker missing')
    assert(not native_fs.access(fixture.state .. '/seeded-config'), 'seed marker was not removed')
    assert(fixture.chmod_calls == 1, 'candidate did not call real native chmod for completion marker')
    assert(native_fs.lstat(fixture.state .. '/migration-v1.done').modestr == 'rw-------',
        'native chmod did not produce mode 600')
    cursor = nil
    collectgarbage('collect')
    local first_snapshot = snapshot(fixture)
    execute_in_fixture(fixture)
    assert(equal(snapshot(fixture), first_snapshot), 'completed repeat was not a byte-for-byte no-op')
    assert(fixture.chmod_calls == 1, 'completed repeat unexpectedly rewrote completion marker')
    print('PASS ' .. case.name .. ': native UCI, private SS preserved, repeat no-op')
end

mkdir(root)
for _, case in ipairs(cases) do run_case(case) end
print('PASS all synthetic native-UCI migration checks; no production configuration used')
print('Sandbox retained for inspection: ' .. root)
