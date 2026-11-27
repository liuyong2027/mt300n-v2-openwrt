local model = dofile('package/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/model.lua')
local settings = {
    mode = 'global',
    server = 'primary.example.com',
    server2 = 'backup1.example.com',
    server3 = 'backup2.example.com',
    auth = 'eap',
    username = 'test',
    password = 'test',
}

local function connection(config, name)
    return assert(config:match('  ' .. name .. ' {\n(.-)    vips ='), name)
end

local defaults = model.swanctl(settings)
assert(not defaults:find('remote_port =', 1, true))
assert(not defaults:find('local_port =', 1, true))
settings.remote_port, settings.remote_port2, settings.remote_port3 = '', '', ''
assert(model.swanctl(settings) == defaults)

settings.remote_port = '500'
local primary = connection(model.swanctl(settings), 'mango')
assert(primary:find('remote_port = 500\n', 1, true))
assert(not primary:find('local_port =', 1, true))

settings.remote_port, settings.remote_port2, settings.remote_port3 = '24450', '1', '65535'
local config = model.swanctl(settings)
for name, port in pairs({mango = 24450, mango2 = 1, mango3 = 65535}) do
    local block = connection(config, name)
    assert(block:find('remote_port = ' .. port .. '\n', 1, true), name)
    assert(block:find('local_port = 4500\n', 1, true), name)
end

settings.server2 = ''
settings.remote_port3 = '24452'
config = model.swanctl(settings)
assert(not config:find('mango2 {', 1, true))
assert(connection(config, 'mango3'):find('remote_port = 24452\n', 1, true))

for _, bad in ipairs({'0', '65536', '-4', '24.5', '1e3', '80 x'}) do
    settings.remote_port3 = bad
    assert(not pcall(model.swanctl, settings), bad)
end
print('PASS test_ikev2_remote_ports.lua')
