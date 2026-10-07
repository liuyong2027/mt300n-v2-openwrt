local M={tag='cudy-ss-zt'}
function M.ip(value)
    if type(value)~='string' then return end
    local a,b,c,d=value:match('^(%d+)%.(%d+)%.(%d+)%.(%d+)$')
    local out={a,b,c,d}; if not a then return end
    for i,v in ipairs(out) do
        if tostring(tonumber(v))~=v or tonumber(v)>255 then return end
        out[i]=tonumber(v)
    end
    return out
end
function M.scope(raw)
    local ip=M.ip(raw.listen); local network,prefix=(raw.subnet or ''):match('^([^/]+)/(%d+)$')
    local subnet=M.ip(network)
    assert(ip and subnet and prefix=='24','Only a valid ZeroTier IPv4 /24 is allowed')
    assert(ip[1]==subnet[1] and ip[2]==subnet[2] and ip[3]==subnet[3] and subnet[4]==0 and ip[4]>0 and ip[4]<255,'Listen address must belong to the authorized subnet')
    assert((ip[1]==10 or (ip[1]==172 and ip[2]>=16 and ip[2]<=31) or (ip[1]==192 and ip[2]==168)),'Listen address must be private IPv4')
    assert(type(raw.interface)=='string' and raw.interface:match('^zt[%w]+$') and #raw.interface<=15,'Invalid ZeroTier interface')
    assert(type(raw.network_id)=='string' and raw.network_id:match('^%x+$') and #raw.network_id==16,'Invalid ZeroTier network ID')
    return {listen=raw.listen,subnet=raw.subnet,interface=raw.interface,network_id=raw.network_id}
end
function M.validate(raw)
    if not raw or raw.enabled~='1' then return nil end
    local c=M.scope(raw)
    local port=tonumber(raw.port)
    assert(port and port==math.floor(port) and port>=1024 and port<=65535 and not ({[1053]=true,[10808]=true,[10809]=true,[10810]=true,[12345]=true})[port],'Invalid or reserved port')
    assert(raw.method=='aes-128-gcm' or raw.method=='aes-256-gcm' or raw.method=='chacha20-ietf-poly1305','An authenticated SS cipher is required')
    assert(type(raw.password)=='string' and #raw.password>=24 and #raw.password<=128 and not raw.password:find('[%c]'),'A strong generated password is required')
    c.port=port; c.method=raw.method; c.password=raw.password
    return c
end
function M.select(raw,networks)
    local copy={};for k,v in pairs(raw or {}) do copy[k]=v end
    if copy.listen or copy.subnet or copy.interface or copy.network_id then return copy end
    local found={}
    for _,net in ipairs(networks or {}) do
        if net.type=='PRIVATE' and net.status=='OK' then
            for _,address in ipairs(net.assignedAddresses or {}) do
                local ip,prefix=address:match('^([^/]+)/(%d+)$');local oct=M.ip(ip)
                if oct and prefix=='24' then
                    local scope={listen=ip,subnet=table.concat({oct[1],oct[2],oct[3],0},'.')..'/24',interface=net.portDeviceName,network_id=net.id}
                    if pcall(M.scope,scope) then found[#found+1]=scope end
                end
            end
        end
    end
    if #found==1 then for k,v in pairs(found[1]) do copy[k]=v end end
    return copy
end
function M.available(c,networks)
    if not c or type(networks)~='table' then return false end
    for _,n in ipairs(networks) do
        if n.id==c.network_id and n.type=='PRIVATE' and n.status=='OK' and n.portDeviceName==c.interface then
            for _,address in ipairs(n.assignedAddresses or {}) do if address==c.listen..'/24' then return true end end
        end
    end
    return false
end
function M.augment(config,c,available)
    assert(type(config)=='table' and type(config.inbounds)=='table' and type(config.outbounds)=='table','Invalid base Xray configuration')
    for _,inbound in ipairs(config.inbounds) do assert(inbound.tag~=M.tag,'SS inbound already present') end
    if not c or not available then return config end
    for _,inbound in ipairs(config.inbounds) do assert(tonumber(inbound.port)~=c.port,'SS port conflicts with an existing listener') end
    config.inbounds[#config.inbounds+1]={tag=M.tag,listen=c.listen,port=c.port,protocol='shadowsocks',
        settings={method=c.method,password=c.password,network='tcp,udp'},
        sniffing={enabled=true,destOverride={'http','tls'},routeOnly=true}}
    return config
end
function M.matches(config,c,wanted)
    local found
    for _,v in ipairs(config and config.inbounds or {}) do
        if v.tag==M.tag then
            if found then return false end
            found=v
        end
    end
    if not wanted then return found==nil end
    return c and found and found.listen==c.listen and tonumber(found.port)==c.port and
        found.protocol=='shadowsocks' and found.settings and found.settings.method==c.method and
        found.settings.password==c.password and found.settings.network=='tcp,udp' or false
end
function M.request(raw,input,networks)
    assert(type(input)=='table','Invalid settings')
    for key in pairs(input) do assert(key=='enabled' or key=='port' or key=='method' or key=='password','Unexpected setting') end
    assert(type(input.enabled)=='boolean' and type(input.port)=='number' and type(input.method)=='string' and type(input.password)=='string','Invalid setting type')
    local copy={}; for k,v in pairs(raw or {}) do copy[k]=v end
    if input.enabled then copy=M.select(copy,networks) end
    copy.enabled='1'; copy.port=tostring(input.port); copy.method=input.method
    if input.password~='' then copy.password=input.password end
    if input.enabled or copy.password then M.validate(copy)
    else
        assert(input.port==math.floor(input.port) and input.port>=1024 and input.port<=65535 and not ({[1053]=true,[10808]=true,[10809]=true,[10810]=true,[12345]=true})[input.port],'Invalid port')
        assert(input.method=='aes-128-gcm' or input.method=='aes-256-gcm' or input.method=='chacha20-ietf-poly1305','Invalid cipher')
    end
    copy.enabled=input.enabled and '1' or '0'
    return copy
end
function M.guard(c)
    if not c then return 'destroy table inet cudy_ss_zt\n' end
    local match='ip daddr '..c.listen..' meta l4proto { tcp, udp } th dport '..c.port
    return 'destroy table inet cudy_ss_zt\ntable inet cudy_ss_zt {\n chain input {\n type filter hook input priority -15; policy accept;\n '..
        match..' iifname != "'..c.interface..'" counter drop\n '..
        match..' ip saddr != '..c.subnet..' counter drop\n }\n}\n'
end
function M.bridge(old,candidate)
    local text='destroy table inet cudy_ss_retired\ntable inet cudy_ss_retired {\n chain input {\n type filter hook input priority -16; policy accept;\n'
    for _,r in ipairs({old,candidate}) do
        local c=M.validate(r)
        if c then
            local match='ip daddr '..c.listen..' meta l4proto { tcp, udp } th dport '..c.port
            text=text..match..' iifname != "'..c.interface..'" counter drop\n'..match..' ip saddr != '..c.subnet..' counter drop\n'
        end
    end
    return text..' }\n}\n'
end
return M
