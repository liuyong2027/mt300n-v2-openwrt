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
    local private_model = dofile('/usr/lib/cudy-ss/ss-zt.lua')
    local private_config = dofile('/usr/lib/cudy-ss/config.lua')
    local json = require('luci.jsonc')
    local sys = require('luci.sys')
    local networks = json.parse(sys.exec('timeout 3 zerotier-cli -j listnetworks 2>/dev/null') or '')
    if type(networks) ~= 'table' then networks = {} end
    local scope_fields = {network_id='cudy_zt_network_id', interface='cudy_zt_interface',
        listen='cudy_zt_listen', subnet='cudy_zt_subnet'}
    local function token(scope)
        return table.concat({scope.network_id, scope.interface, scope.listen, scope.subnet}, '|')
    end
    local choices, labels = {}, {}
    local function add(scope, suffix)
        local id = token(scope)
        choices[id] = scope
        labels[id] = scope.network_id .. ' / ' .. scope.listen .. ' / ' .. scope.interface ..
            ' / ' .. scope.subnet .. suffix
        return id
    end
    local valid_scope, existing = pcall(private_model.scope, private_config.server_raw(cudy_raw))
    local existing_token = valid_scope and add(existing, ' (' .. translate('current approval') .. ')') or nil
    for _, network in ipairs(networks) do
        if network.type == 'PRIVATE' and network.status == 'OK' then
            for _, address in ipairs(network.assignedAddresses or {}) do
                local ip, prefix = address:match('^([^/]+)/(%d+)$')
                local octets = ip and private_model.ip(ip)
                if octets and prefix == '24' then
                    local scope = {network_id=network.id, interface=network.portDeviceName, listen=ip,
                        subnet=table.concat({octets[1],octets[2],octets[3],0}, '.') .. '/24'}
                    if pcall(private_model.scope, scope) and private_model.available(scope, networks) then
                        local id = token(scope)
                        if not choices[id] then add(scope, '') end
                    end
                end
            end
        end
    end
    o = s:option(ListValue, '_cudy_zt_approval', translate('Approve ZeroTier private access'))
    if not existing_token then o:value('', translate('Choose a connected private ZeroTier IPv4 /24')) end
    for id, label in pairs(labels) do o:value(id, label) end
    o.default = ''
    o.rmempty = true
    o.description = translate('Saving a selected network approves the displayed interface, IPv4 address and source subnet. It does not enable this server or the global server switch.')
    function o.cfgvalue(self, section) return existing_token or '' end
    function o.validate(self, value, section)
        if value == '' and not existing_token then return value end
        if not choices[value] then return nil, translate('Choose a currently connected private ZeroTier IPv4 /24') end
        return value
    end
    function o.write(self, section, value)
        -- Virtual option: credentials and enable switches are never written here.
        if not value or value == '' or value == existing_token then return end
        local scope = assert(choices[value])
        assert(private_model.available(scope, networks), 'The selected private ZeroTier network is unavailable')
        for key, field in pairs(scope_fields) do
            assert(self.map.uci:set('shadowsocksr', section, field, scope[key]))
        end
    end
    function o.remove(self, section) end

    local function candidate(self, value, section)
        local row = {}
        for key, item in pairs(self.map.uci:get_all('shadowsocksr', section) or {}) do row[key] = item end
        for _, field in ipairs({'enable','type','server_port','ss_method','ss_password','ss_network','cudy_access'}) do
            local posted = self.map:formvalue('cbid.shadowsocksr.' .. section .. '.' .. field)
            if posted ~= nil then row[field] = posted end
        end
        if self.map:formvalue('cbi.cbe.shadowsocksr.' .. section .. '.enable') then
            row.enable = self.map:formvalue('cbid.shadowsocksr.' .. section .. '.enable') and '1' or '0'
        end
        if self.option ~= '_cudy_zt_approval' then row[self.option] = value end
        local approval = self.option == '_cudy_zt_approval' and value or
            self.map:formvalue('cbid.shadowsocksr.' .. section .. '._cudy_zt_approval')
        if approval and approval ~= '' then
            local scope = assert(choices[approval], 'Unknown or unavailable private ZeroTier approval')
            for key, field in pairs(scope_fields) do row[field] = scope[key] end
        elseif approval == '' and existing_token then
            error('The existing approved scope must be retained or explicitly replaced')
        end
        assert(row.type == 'shadowsocks' and row.cudy_private == '1' and row.cudy_access == 'zerotier',
            'The reserved private service must retain its Shadowsocks identity and private scope')
        local raw = private_config.server_raw(row)
        local has_scope = false
        for _, field in pairs(scope_fields) do
            if row[field] and row[field] ~= '' then has_scope = true end
        end
        local fresh_off = row.enable ~= '1' and not has_scope and (not raw.password or raw.password == '')
        private_model.private_credentials(raw, fresh_off)
        if not fresh_off then raw.enabled = '1' end
        private_config.validate(raw, private_model.validate)
    end
    -- CBI parses enable before credentials. Every validator sees the entire
    -- submitted form, so a new approval and password can be saved together.
    for _, name in ipairs({'enable','type','server_port','ss_password','ss_method','ss_network','cudy_access','_cudy_zt_approval'}) do
        local field = assert(s.fields[name])
        local previous = field.validate
        field.validate = function(self, value, section)
            local valid, problem = pcall(candidate, self, value, section)
            if not valid then return nil, tostring(problem) end
            if previous then return previous(self, value, section) end
            return value
        end
    end
    -- An unconfigured disabled row may retain an absent password. The enable
    -- and approval validators still reject activation without credentials.
    s.fields.ss_password.rmempty = true
    for _, field in ipairs({{'cudy_zt_network_id','Approved ZeroTier Network'},
        {'cudy_zt_interface','Approved ZeroTier Interface'}, {'cudy_zt_listen','Approved Listen Address'},
        {'cudy_zt_subnet','Approved Source Subnet'}}) do
        o = s:option(DummyValue, field[1], translate(field[2]))
    end
end
