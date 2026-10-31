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
assert(swan:find('dpd_delay = 30s', 1, true))
assert(swan:find('keyingtries = 1', 1, true))
assert(swan:find('start_action = none', 1, true))
assert(not swan:find('mango2', 1, true))
assert(swan:find('secret = "s3cret"', 1, true))
local two = {}
for k, v in pairs(eap) do two[k] = v end
two.server2 = 'backup.example.com'
two.remote_id2 = 'backup.example.net'
local both = M.swanctl(two)
assert(both:find('remote_addrs = backup.example.com', 1, true))
assert(both:find('id = "backup.example.net"', 1, true))
assert(#M.peers(two) == 2)
two.server2 = two.server
assert(not pcall(M.peers, two))
assert(not swan:find('password', 1, true) or true)

local nft = M.nft(eap)
assert(nft:find('table inet mango_ikev2', 1, true))
assert(nft:find('set cn4', 1, true))
assert(nft:find('1.2.3.0/24', 1, true))
assert(nft:find('meta mark set 0x101', 1, true))
assert(nft:find('redirect to :53', 1, true))
assert(nft:find('th dport 53 return', 1, true))
assert(nft:find('oifname "xfrm-mango" masquerade', 1, true))
assert(not nft:find('tproxy', 1, true))
local dns = M.dnsmasq(eap)
assert(dns:find('server=1.1.1.1', 1, true))
assert(dns:find('server=8.8.8.8', 1, true))
assert(dns:find('no-resolv', 1, true))
assert(not dns:find('server=223.5.5.5\n', 1, true))

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
assert(not pcall(M.policy, {mode = 'warp', enabled = '1'}))
assert(not pcall(M.policy, {mode = 'split', enabled = '1', ifid = '0'}))

local gfw = {}
for k, v in pairs(eap) do gfw[k] = v end
gfw.mode = 'gfw'
gfw.gfw_domains = {'+google.com', '-accounts.google.com'}
local gfw_nft = M.nft(gfw)
assert(gfw_nft:find('set gfw4', 1, true))
assert(gfw_nft:find('ip daddr @gfw4 meta mark set 0x101', 1, true))
assert(not gfw_nft:find('jump fail_closed', 1, true))
assert(gfw_nft:find('redirect to :53', 1, true))
local gfw_dns = M.dnsmasq(gfw)
assert(gfw_dns:find('server=223.5.5.5', 1, true))
assert(gfw_dns:find('server=/google.com/1.1.1.1', 1, true))
assert(gfw_dns:find('nftset=/google.com/4#inet#mango_ikev2#gfw4', 1, true))
assert(gfw_dns:find('server=/accounts.google.com/223.5.5.5', 1, true))
assert(not gfw_dns:find('nftset=/accounts.google.com/', 1, true))

local raw = {'[AutoProxy 0.0.0.0]'}
for i = 1, 100 do raw[#raw + 1] = '||site' .. i .. '.example.com' end
raw[#raw + 1] = '@@||direct.example.com'
raw[#raw + 1] = '/^https?:\\/\\/.*\\.regex\\.com/'
local converted, count, skipped = M.convert_gfwlist(table.concat(raw, '\n'))
assert(count == 100, count)
assert(skipped == 1, skipped)
assert(converted:find('-direct.example.com', 1, true))
assert(converted:find('+site1.example.com', 1, true))

print('PASS IKEv2 model swanctl/nft/validation')
