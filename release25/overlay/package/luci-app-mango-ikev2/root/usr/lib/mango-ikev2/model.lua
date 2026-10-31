-- MIT. Pure IKEv2 client policy helpers shared by router and host tests.
local M = {}

local private = {
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
    '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/3'
}

local function nonempty(v)
    return type(v) == 'string' and v ~= ''
end

function M.ip4(v)
    if type(v) ~= 'string' then return false end
    local ip, prefix = v:match('^([%d%.]+)/(%d+)$')
    if not ip then ip = v end
    local a, b, c, d = ip:match('^(%d+)%.(%d+)%.(%d+)%.(%d+)$')
    if not a then return false end
    for _, n in ipairs({a, b, c, d}) do
        if #n > 3 or tonumber(n) > 255 or (#n > 1 and n:sub(1, 1) == '0') then
            return false
        end
    end
    return not prefix or tonumber(prefix) <= 32
end

local function host(v)
    return type(v) == 'string' and #v > 0 and #v <= 253 and v:match('^[%w][%w%.%-]*$') ~= nil
end

function M.domain(v)
    return type(v) == 'string' and #v <= 253 and v:match('^[a-z0-9][a-z0-9%.%-]*%.[a-z][a-z]+$') ~= nil
end

local function escape(v)
    return (tostring(v):gsub('\\', '\\\\'):gsub('"', '\\"'))
end

-- Tunnel resolvers are never domestic. Router-originated queries use /32 routes
-- via xfrm; LAN queries are redirected to local dnsmasq first.
M.tunnel_dns = {'1.1.1.1', '8.8.8.8'}
M.domestic_dns = {'223.5.5.5', '119.29.29.29'}

function M.policy(p)
    assert(p.mode == 'direct' or p.mode == 'split' or p.mode == 'global' or p.mode == 'gfw', 'Invalid mode')
    local lan = p.lan_device or 'br-lan'
    assert(#lan <= 15 and lan:match('^[%w_.%-]+$'), 'Invalid LAN device')
    local ifid = tonumber(p.ifid or '42')
    assert(ifid and ifid == math.floor(ifid) and ifid >= 1 and ifid <= 65535, 'Invalid XFRM ifid')
    local mtu = tonumber(p.xfrm_mtu or '1280')
    assert(mtu and mtu == math.floor(mtu) and mtu >= 1280 and mtu <= 1500, 'Invalid XFRM MTU')
    local bypass = {}
    for _, ip in ipairs(private) do bypass[#bypass + 1] = ip end
    return {
        enabled = p.enabled == '1' or p.enabled == true,
        mode = p.mode,
        lan = lan,
        ifid = ifid,
        mtu = mtu,
        bypass = bypass,
        active = (p.enabled == '1' or p.enabled == true) and p.mode ~= 'direct'
    }
end

function M.credentials(p)
    assert(host(p.server), 'Invalid server')
    local auth = p.auth or 'eap'
    assert(auth == 'eap' or auth == 'psk', 'Unsupported auth')
    local remote_id = nonempty(p.remote_id) and p.remote_id or p.server
    assert(host(remote_id) or nonempty(remote_id), 'Invalid remote ID')
    local local_id = p.local_id or ''
    if auth == 'eap' then
        assert(nonempty(p.username), 'Missing EAP username')
        assert(nonempty(p.password), 'Missing EAP password')
        if local_id == '' then local_id = p.username end
    else
        assert(nonempty(p.psk), 'Missing PSK')
        if local_id == '' then local_id = '%any' end
    end
    assert(not tostring(p.username or ''):find('[%z\r\n"]'), 'Invalid username chars')
    assert(not tostring(p.password or ''):find('[%z\r\n]'), 'Invalid password chars')
    assert(not tostring(p.psk or ''):find('[%z\r\n]'), 'Invalid PSK chars')
    return {
        server = p.server,
        remote_id = remote_id,
        local_id = local_id,
        auth = auth,
        username = p.username or '',
        password = p.password or '',
        psk = p.psk or ''
    }
end

function M.peers(p)
    local cred = M.credentials(p)
    local peers = {{name = 'mango', server = cred.server, remote_id = cred.remote_id, cred = cred}}
    local backup = p.server2
    if type(backup) == 'string' and backup ~= '' then
        assert(host(backup), 'Invalid backup server')
        assert(backup ~= cred.server, 'Backup server must differ from the primary')
        local remote2 = (type(p.remote_id2) == 'string' and p.remote_id2 ~= '') and p.remote_id2 or backup
        assert(host(remote2) or nonempty(remote2), 'Invalid backup remote ID')
        peers[#peers + 1] = {name = 'mango2', server = backup, remote_id = remote2, cred = cred}
    end
    return peers
end

function M.swanctl(p)
    local q = M.policy(p)
    local peers = M.peers(p)
    local c = peers[1].cred
    local lines = {'connections {'}
    for _, peer in ipairs(peers) do
        lines[#lines + 1] = '  ' .. peer.name .. ' {'
        lines[#lines + 1] = '    version = 2'
        lines[#lines + 1] = '    remote_addrs = ' .. escape(peer.server)
        lines[#lines + 1] = '    vips = 0.0.0.0'
        lines[#lines + 1] = '    keyingtries = 1'
        lines[#lines + 1] = '    dpd_delay = 30s'
        lines[#lines + 1] = '    dpd_timeout = 30s'
        lines[#lines + 1] = '    local {'
        lines[#lines + 1] = '      id = "' .. escape(c.local_id) .. '"'
        if c.auth == 'eap' then
            lines[#lines + 1] = '      auth = eap-mschapv2'
            lines[#lines + 1] = '      eap_id = "' .. escape(c.username) .. '"'
        else
            lines[#lines + 1] = '      auth = psk'
        end
        lines[#lines + 1] = '    }'
        lines[#lines + 1] = '    remote {'
        lines[#lines + 1] = '      id = "' .. escape(peer.remote_id) .. '"'
        if c.auth == 'eap' then
            lines[#lines + 1] = '      auth = pubkey'
        else
            lines[#lines + 1] = '      auth = psk'
        end
        lines[#lines + 1] = '    }'
        lines[#lines + 1] = '    children {'
        lines[#lines + 1] = '      ' .. peer.name .. ' {'
        lines[#lines + 1] = '        local_ts = 0.0.0.0/0'
        lines[#lines + 1] = '        remote_ts = 0.0.0.0/0'
        -- The watcher counts failures and switches servers. Charon must not redial by itself.
        lines[#lines + 1] = '        start_action = none'
        lines[#lines + 1] = '        close_action = none'
        lines[#lines + 1] = '        dpd_action = clear'
        lines[#lines + 1] = '        if_id_in = ' .. tostring(q.ifid)
        lines[#lines + 1] = '        if_id_out = ' .. tostring(q.ifid)
        lines[#lines + 1] = '      }'
        lines[#lines + 1] = '    }'
        lines[#lines + 1] = '  }'
    end
    lines[#lines + 1] = '}'
    lines[#lines + 1] = 'secrets {'
    if c.auth == 'eap' then
        lines[#lines + 1] = '  eap-mango {'
        lines[#lines + 1] = '    id = "' .. escape(c.username) .. '"'
        lines[#lines + 1] = '    secret = "' .. escape(c.password) .. '"'
        lines[#lines + 1] = '  }'
    else
        lines[#lines + 1] = '  ike-mango {'
        lines[#lines + 1] = '    id = "' .. escape(c.local_id) .. '"'
        lines[#lines + 1] = '    secret = "' .. escape(c.psk) .. '"'
        lines[#lines + 1] = '  }'
    end
    lines[#lines + 1] = '}'
    return table.concat(lines, '\n') .. '\n'
end

-- GFWList text -> +domain / -domain lines. Rejects wildcards, paths and regex.
function M.convert_gfwlist(text)
    assert(type(text) == 'string' and #text <= 512 * 1024 and text:find('[AutoProxy', 1, true), 'Invalid GFWList')
    local proxy, direct, skipped = {}, {}, 0
    for line in text:gmatch('[^\r\n]+') do
        line = line:match('^%s*(.-)%s*$')
        if line ~= '' and line:sub(1, 1) ~= '!' and line:sub(1, 1) ~= '[' then
            local except = line:sub(1, 2) == '@@'
            if except then line = line:sub(3) end
            line = line:gsub('^||', ''):gsub('^|', ''):gsub('^https?://', ''):gsub('^%.', '')
            line = line:gsub('[%^|]$', ''):gsub('/$', ''):lower()
            if M.domain(line) then
                if except then direct[line] = true else proxy[line] = true end
            else
                skipped = skipped + 1
            end
        end
    end
    local output, count = {}, 0
    for domain in pairs(direct) do output[#output + 1] = '-' .. domain end
    for domain in pairs(proxy) do
        if not direct[domain] then
            output[#output + 1] = '+' .. domain
            count = count + 1
        end
    end
    assert(count >= 100 and count <= 20000, 'Unexpected GFW domain count')
    table.sort(output)
    return table.concat(output, '\n') .. '\n', count, skipped
end

function M.dnsmasq(p)
    local q = M.policy(p)
    if not q.active then return '' end
    local lines = {'no-resolv', 'filter-AAAA'}
    local function add(s) lines[#lines + 1] = s end
    if q.mode == 'gfw' then
        for _, address in ipairs(M.domestic_dns) do add('server=' .. address) end
        local seen = {}
        for _, line in ipairs(p.gfw_domains or {}) do
            local flag, name = line:match('^([+-])([a-z0-9%.%-]+)$')
            if name and not seen[name] and M.domain(name) then
                seen[name] = true
                if flag == '+' then
                    for _, address in ipairs(M.tunnel_dns) do
                        add('server=/' .. name .. '/' .. address)
                    end
                    add('nftset=/' .. name .. '/4#inet#mango_ikev2#gfw4')
                else
                    for _, address in ipairs(M.domestic_dns) do
                        add('server=/' .. name .. '/' .. address)
                    end
                end
            end
        end
    else
        -- split/global: domestic resolvers are not queried, so a poisoned answer cannot win.
        for _, address in ipairs(M.tunnel_dns) do add('server=' .. address) end
    end
    return table.concat(lines, '\n') .. '\n'
end

function M.nft(p)
    local q = M.policy(p)
    local cn = {}
    if q.mode == 'split' then
        for _, cidr in ipairs(p.cn_cidrs or {}) do
            if cidr ~= '0.0.0.0/0' and M.ip4(cidr) then
                cn[#cn + 1] = cidr
            end
        end
    end
    local lines = {
        'add table inet mango_ikev2',
        'flush table inet mango_ikev2',
        'table inet mango_ikev2 {',
        'set bypass4 { type ipv4_addr; flags interval; auto-merge; elements = { ' ..
            table.concat(q.bypass, ', ') .. ' } }'
    }
    local function add(s) lines[#lines + 1] = s end
    if #cn > 0 then
        add('set cn4 { type ipv4_addr; flags interval; auto-merge; elements = { ' ..
            table.concat(cn, ', ') .. ' } }')
    end
    if q.mode == 'gfw' and q.active then
        -- Filled by dnsmasq nftset after a GFW domain resolves through the tunnel.
        add('set gfw4 { type ipv4_addr; flags timeout; timeout 2h; }')
    end
    add('chain guard { type filter hook forward priority -10; policy accept;')
    if q.active and q.mode ~= 'gfw' then
        add('iifname "' .. q.lan .. '" jump fail_closed')
    end
    add('}')
    add('chain fail_closed {')
    add('ip daddr @bypass4 return')
    if #cn > 0 then add('ip daddr @cn4 return') end
    add('oifname "xfrm-mango" return')
    add('ip6 daddr { fc00::/7, fe80::/10, ff00::/8 } return')
    -- split/global: public destinations outside the tunnel must not leak.
    add('drop\n}')
    if q.active then
        add('chain capture {')
        add('fib daddr type local return')
        add('ip daddr @bypass4 return')
        if #cn > 0 then add('ip daddr @cn4 return') end
        if q.mode == 'gfw' then
            add('ip daddr @gfw4 meta mark set 0x101 accept')
        else
            add('meta nfproto ipv4 meta mark set 0x101 accept')
        end
        add('}')
        add('chain prerouting { type filter hook prerouting priority -160; policy accept;')
        add('ct direction reply return')
        -- Port 53 is hijacked to local dnsmasq and must not enter the tunnel itself.
        add('meta l4proto { tcp, udp } th dport 53 return')
        add('iifname "' .. q.lan .. '" jump capture')
        add('}')
        add('chain dns_capture { type nat hook prerouting priority -105; policy accept;')
        add('iifname "' .. q.lan .. '" meta nfproto ipv4 meta l4proto { tcp, udp } th dport 53 redirect to :53')
        add('}')
        add('chain postrouting { type nat hook postrouting priority srcnat; policy accept;')
        add('oifname "xfrm-mango" masquerade')
        add('}')
    end
    add('}')
    return table.concat(lines, '\n') .. '\n'
end

return M
