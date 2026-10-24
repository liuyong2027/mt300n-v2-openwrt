-- Access Scope applies to encrypted ingress. Decrypted TCP/UDP are processed
-- by the SSR client policy through the shared internal client interface.
o = s:option(ListValue, 'cudy_access', translate('Access Scope'))
o:value('loopback', translate('Router only (loopback)'))
o:value('lan', translate('LAN only'))
o:value('public', translate('Public access (explicitly allow)'))
o.default='loopback'
o.rmempty=false
o.description=translate('Access Scope controls who may connect. Shadowsocks decrypted TCP and UDP follow the SSR Plus+ client policy and selected proxy ports.')
function o.cfgvalue(self, section)
    local raw=self.map.uci:get_all('shadowsocksr',section) or {}
    return raw.cudy_access or (raw.bind_local=='1' and 'loopback' or (raw.accept_lan=='1' and 'lan' or 'loopback'))
end
function o.validate(self,value,section)
    if value~='loopback' and value~='lan' and value~='public' then return nil,translate('Invalid access scope') end
    return value
end
