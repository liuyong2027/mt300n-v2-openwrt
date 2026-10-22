-- Actual server exposure is enforced by cudy-ssr-server-firewall before fw4.
local cudy_server = require('cudy.ssr-server')
local cudy_raw = m.uci:get_all('shadowsocksr', sid) or {}
cudy_raw['.name'] = sid
local cudy_private = cudy_server.private(cudy_raw)
o = s:option(ListValue, 'cudy_access', translate('Access Scope'))
if cudy_private then
    o:value('zerotier', translate('Approved ZeroTier private network only'))
    o.default = 'zerotier'
    o.description = translate('The approved interface, address and source subnet are retained. This server uses the isolated private runtime.')
else
    o:value('loopback', translate('Router only (loopback)'))
    o:value('lan', translate('LAN only'))
    o:value('public', translate('Public access (explicitly allow)'))
    o.default = 'loopback'
    o.description = translate('LAN permits IPv4 only on the active LAN interface and address. Public access opens the selected server transport to other networks.')
end
o.rmempty = false
function o.cfgvalue(self, section)
    local raw = self.map.uci:get_all('shadowsocksr', section) or {}
    raw['.name'] = section
    if cudy_server.private(raw) then return 'zerotier' end
    return raw.cudy_access or (raw.bind_local == '1' and 'loopback' or (raw.accept_lan == '1' and 'lan' or 'loopback'))
end
function o.validate(self, value, section)
    if cudy_private then
        if value ~= 'zerotier' then return nil, translate('Approved private scope cannot be broadened here') end
    elseif value ~= 'loopback' and value ~= 'lan' and value ~= 'public' then
        return nil, translate('Invalid access scope')
    end
    return value
end
if cudy_private then
    for _, field in ipairs({{'cudy_zt_network_id','Approved ZeroTier Network'},
        {'cudy_zt_interface','Approved ZeroTier Interface'}, {'cudy_zt_listen','Approved Listen Address'},
        {'cudy_zt_subnet','Approved Source Subnet'}}) do
        o = s:option(DummyValue, field[1], translate(field[2]))
    end
end
