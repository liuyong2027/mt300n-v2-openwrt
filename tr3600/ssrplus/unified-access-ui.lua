-- Access Scope applies to every server type. Only ordinary Shadowsocks uses
-- the shared internal client interface for decrypted TCP/UDP policy routing.
o = s:option(ListValue, 'cudy_access', translate('Access Scope'))
o:value('loopback', translate('Router only (loopback)'))
o:value('lan', translate('LAN only'))
o:value('public', translate('Public access (explicitly allow)'))
o.default='loopback'
o.rmempty=false
o.description=translate('Access Scope controls who may connect.')
function o.cfgvalue(self, section)
    local raw=self.map.uci:get_all('shadowsocksr',section) or {}
    return raw.cudy_access or (raw.bind_local=='1' and 'loopback' or (raw.accept_lan=='1' and 'lan' or 'loopback'))
end
function o.validate(self,value,section)
    if value~='loopback' and value~='lan' and value~='public' then return nil,translate('Invalid access scope') end
    return value
end

-- CBI dependencies update the explanation immediately when the type changes.
-- DummyValue fields are display-only and never write options to UCI.
local cudy_ss_note=s:option(DummyValue, '_cudy_ss_policy_note', translate('Traffic handling'))
cudy_ss_note.default=translate('Shadowsocks decrypted TCP and UDP follow the SSR Plus+ client policy and selected proxy ports.')
cudy_ss_note:depends('type', 'shadowsocks')
local cudy_other_note=s:option(DummyValue, '_cudy_other_policy_note', translate('Traffic handling'))
cudy_other_note.default=translate("This server's traffic follows the router's own outbound policy.")
cudy_other_note:depends({type='shadowsocks', ['!reverse']=true})
