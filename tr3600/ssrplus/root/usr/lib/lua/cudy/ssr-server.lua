-- Shared validation and generation for SSR Plus+ host-namespace servers.
local M={}
M.methods={'aes-128-gcm','aes-256-gcm','chacha20-ietf-poly1305','xchacha20-ietf-poly1305',
    '2022-blake3-aes-128-gcm','2022-blake3-aes-256-gcm','2022-blake3-chacha20-poly1305'}
local aliases={['aead_aes_128_gcm']='aes-128-gcm',['aead_aes_256_gcm']='aes-256-gcm',
    ['chacha20-poly1305']='chacha20-ietf-poly1305',['aead_chacha20_poly1305']='chacha20-ietf-poly1305',
    ['xchacha20-poly1305']='xchacha20-ietf-poly1305',['aead_xchacha20_poly1305']='xchacha20-ietf-poly1305'}
local methods={}
for _,method in ipairs(M.methods) do methods[method]=true end
local networks={tcp=true,udp=true,['tcp,udp']=true}
local scopes={loopback=true,lan=true,public=true}
local function integer(value)
    local number=tonumber(value)
    return number and number==math.floor(number) and number>=1 and number<=65535 and number or nil
end
local function ipv4(value)
    if type(value)~='string' or not value:match('^%d+%.%d+%.%d+%.%d+$') then return false end
    for part in value:gmatch('%d+') do
        if tonumber(part)>255 or (#part>1 and part:sub(1,1)=='0') then return false end
    end
    return true
end
M.ipv4=ipv4
function M.private(raw)
    return raw['.name']=='cudy_zt_private' or raw.cudy_private=='1' or raw.cudy_access=='zerotier'
end
function M.method(method,password)
    method=method or 'chacha20-ietf-poly1305'
    method=aliases[method] or method
    assert(methods[method], 'Unsupported SS cipher in this Xray version; choose an AEAD or SS2022 method')
    assert(type(password)=='string' and #password>0, 'Shadowsocks password is required')
    if method:match('^2022%-') then
        local size=method=='2022-blake3-aes-128-gcm' and 16 or 32
        local padding=size==16 and 2 or 1
        local expected=size==16 and 24 or 44
        assert(#password==expected and password:match('^[A-Za-z0-9+/]+='..(padding==2 and '=' or '')..'$'),
            'SS2022 requires one standard base64 key with the cipher key length')
        local alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
        local last=password:sub(#password-padding,#password-padding)
        local index=assert(alphabet:find(last,1,true))-1
        assert(index%(padding==2 and 16 or 4)==0, 'SS2022 key has noncanonical base64 padding bits')
    end
    return method
end
function M.normalize(raw)
    assert(type(raw)=='table', 'Missing server_config')
    assert(not M.private(raw), 'ZeroTier private server must use the approved namespace runtime')
    local scope=raw.cudy_access
    if not scope or scope=='' then
        scope=raw.bind_local=='1' and 'loopback' or (raw.accept_lan=='1' and 'lan' or 'loopback')
    end
    assert(scopes[scope], 'Invalid server access scope')
    local port=assert(integer(raw.server_port), 'Invalid server port')
    local result={id=raw['.name'],type=raw.type,scope=scope,port=port,
        listen=scope=='loopback' and '127.0.0.1' or '0.0.0.0',network='tcp,udp'}
    if raw.type=='shadowsocks' then
        assert(raw.tls~='1' and raw.xtls~='1', 'TLS wrapping is not supported by this SS server generator')
        result.password=raw.ss_password
        -- Only the legacy password field is a compatible fallback; security and
        -- transport/network belong to other protocols and must never override SS.
        if not result.password or result.password=='' then result.password=raw.password end
        result.method=M.method(raw.ss_method,result.password)
        result.network=raw.ss_network or 'tcp,udp'
        assert(networks[result.network], 'Invalid SS network; choose tcp, udp or tcp,udp')
    end
    return result
end
function M.config(raw)
    local c=M.normalize(raw)
    assert(c.type=='shadowsocks', 'This generator only handles built-in Xray Shadowsocks')
    return {log={loglevel='warning'},
        inbounds={{tag='ssr-server-'..(c.id or 'ss'),listen=c.listen,port=c.port,protocol='shadowsocks',
            settings={method=c.method,password=c.password,network=c.network}}},
        outbounds={{tag='direct',protocol='freedom',settings={domainStrategy='UseIPv4'}}}}
end
local function condition(c,protocol)
    return protocol..' dport '..c.port
end
local function accepted(c,lan)
    local list={}
    for protocol in c.network:gmatch('[^,]+') do
        local endpoint=condition(c,protocol)
        if c.scope=='loopback' then
            list[#list+1]='iifname "lo" '..(c.type=='shadowsocks' and 'meta nfproto ipv4 ' or '')..endpoint
        elseif c.scope=='public' then
            list[#list+1]=(c.type=='shadowsocks' and 'meta nfproto ipv4 ' or '')..endpoint
        else
            assert(type(lan)=='table' and type(lan.device)=='string' and
                lan.device:match('^[%w_.:-]+$') and #lan.device<=15, 'LAN interface is unavailable or invalid')
            assert(type(lan.addresses)=='table' and #lan.addresses>0, 'LAN IPv4 address is unavailable')
            list[#list+1]='iifname "lo" meta nfproto ipv4 '..endpoint
            for _,address in ipairs(lan.addresses) do
                assert(ipv4(address), 'Invalid LAN IPv4 address')
                list[#list+1]='iifname "'..lan.device..'" ip daddr '..address..' '..endpoint
            end
        end
    end
    return list
end
function M.rules(rows,lan,active)
    local guard={'destroy table inet cudy_ssr_server','table inet cudy_ssr_server {',
        'chain scope { type filter hook input priority -5; policy accept;'}
    local allow={'flush chain inet fw4 CUDY_SSR_SERVER'}
    local seen={}
    for _,raw in ipairs(rows) do
        if raw.enable=='1' then
            local port=assert(integer(raw.server_port), 'Invalid enabled server port')
            assert(not seen[port], 'Enabled server port collision')
            seen[port]=true
            if not M.private(raw) then
                local c=M.normalize(raw)
                assert(type(c.id)=='string' and c.id:match('^[%w_]+$'), 'Invalid server section name')
                local enabled=active==nil or active[c.id]
                for _,match in ipairs(accepted(c,lan)) do
                    -- A return only ends this chain; fw4 still controls INPUT.
                    if enabled then
                        guard[#guard+1]=match..' return'
                        allow[#allow+1]='add rule inet fw4 CUDY_SSR_SERVER '..match..' accept'
                    end
                end
                -- Explicit drops precede fw4's established/zone accepts and
                -- cover wrong scope, IPv6 LAN input and the unselected transport.
                guard[#guard+1]='meta l4proto { tcp, udp } th dport '..c.port..' counter drop'
            end
        end
    end
    guard[#guard+1]='}';guard[#guard+1]='}'
    return table.concat(guard,'\n')..'\n'..table.concat(allow,'\n')..'\n'
end
return M
