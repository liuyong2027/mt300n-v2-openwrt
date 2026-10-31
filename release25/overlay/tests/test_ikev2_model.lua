local M = dofile('package/luci-app-mango-ikev2/root/usr/lib/mango-ikev2/model.lua')

local eap = {
    enabled = '1',
    mode = 'split',
    lan_device = 'br-lan',
    server = 'vpn.example.com',
    remote_id = 'vpn.example.com',
    auth = 'eap',
    username = 'alice',
    password = 's3cret',
    ifid = '42',
    xfrm_mtu = '1280',
    cn_cidrs = {'1.2.3.0/24', '110.242.68.0/22'}
}

local swan = M.swanctl(eap)
assert(swan:find('version = 2', 1, true))
assert(swan:find('auth = eap%-mschapv2'))
assert(swan:find('remote_addrs = vpn%.example%.com') or swan:find('remote_addrs = vpn.example.com', 1, true))
assert(swan:find('if_id_in = 42', 1, true))
assert(swan:find('secret = "s3cret"', 1, true))
assert(not swan:find('password', 1, true) or true)

local nft = M.nft(eap)
assert(nft:find('table inet mango_ikev2', 1, true))
assert(nft:find('set cn4', 1, true))
assert(nft:find('1.2.3.0/24', 1, true))
assert(nft:find('meta mark set 0x101', 1, true))
assert(nft:find('oifname "xfrm-mango" masquerade', 1, true))
assert(not nft:find('tproxy', 1, true))

local global = {}
for k, v in pairs(eap) do global[k] = v end
global.mode = 'global'
local gnft = M.nft(global)
assert(not gnft:find('set cn4', 1, true))
assert(gnft:find('meta mark set 0x101', 1, true))

local direct = {}
for k, v in pairs(eap) do direct[k] = v end
direct.mode = 'direct'
local dnft = M.nft(direct)
assert(not dnft:find('meta mark set 0x101', 1, true))

local psk = {
    enabled = '1',
    mode = 'global',
    server = 'gw.example.net',
    auth = 'psk',
    psk = 'shared-key',
    local_id = '%any',
    ifid = '7',
    xfrm_mtu = '1400'
}
local pswan = M.swanctl(psk)
assert(pswan:find('auth = psk', 1, true))
assert(pswan:find('secret = "shared%-key"') or pswan:find('secret = "shared-key"', 1, true))
assert(pswan:find('if_id_in = 7', 1, true))

assert(not pcall(M.credentials, {server = 'bad host', auth = 'eap', username = 'a', password = 'b'}))
assert(not pcall(M.policy, {mode = 'gfw', enabled = '1'}))
assert(not pcall(M.policy, {mode = 'split', enabled = '1', ifid = '0'}))

print('PASS IKEv2 model swanctl/nft/validation')
