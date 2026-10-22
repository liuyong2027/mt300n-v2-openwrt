-- The namespace makes decrypted SS traffic enter the one SSR Plus+ policy.
local M={}
M.network='198.18.255.0/30'
M.host='198.18.255.1'
M.peer='198.18.255.2'
M.section='cudy_zt_private'
M.tag='cudy-ss-zt'
local function transport(network)
    assert(network=='tcp' or network=='udp' or network=='tcp,udp','Invalid private SS transport')
    return network=='tcp,udp' and '{ tcp, udp }' or network
end
function M.raw(u)
    u=u or require('uci').cursor()
    local row=u:get_all('shadowsocksr',M.section)
    local count=0
    u:foreach('shadowsocksr','server_config',function(s)
        if s.cudy_private=='1' then
            assert(s['.name']==M.section,'Unexpected private SS section')
            count=count+1
        end
    end)
    if not row then assert(count==0,'Missing canonical private SS row');return nil end
    assert(row['.type']=='server_config' and row.type=='shadowsocks' and
        row.cudy_private=='1' and row.cudy_access=='zerotier' and count==1,
        'Invalid private SS server_config metadata')
    transport(row.ss_network)
    local global
    u:foreach('shadowsocksr','server_global',function(s) if not global then global=s end end)
    local global_enabled=global and global.enable_server or '0'
    return {enabled=(row.enable=='1' and global_enabled=='1') and '1' or '0',
        requested_enabled=row.enable,global_enabled=global_enabled,
        port=row.server_port,method=row.ss_method,password=row.ss_password,network=row.ss_network,
        network_id=row.cudy_zt_network_id,interface=row.cudy_zt_interface,
        listen=row.cudy_zt_listen,subnet=row.cudy_zt_subnet}
end
function M.validate(raw,validate)
    if raw then transport(raw.network) end
    local c=validate(raw)
    if c then c.network=raw.network end
    return c
end
function M.config(c)
    transport(c.network)
    return {
        log={loglevel='warning'},
        dns={queryStrategy='UseIPv4',servers={M.host}},
        inbounds={{tag=M.tag,listen='0.0.0.0',port=c.port,protocol='shadowsocks',
            settings={method=c.method,password=c.password,network=c.network},
            sniffing={enabled=true,destOverride={'http','tls'},routeOnly=true}}},
        outbounds={{tag='direct',protocol='freedom',settings={domainStrategy='UseIPv4'}}}
    }
end
function M.matches(config,c,wanted)
    local found
    for _,inbound in ipairs(config and config.inbounds or {}) do
        if inbound.tag==M.tag then
            if found then return false end
            found=inbound
        end
    end
    if not wanted then return found==nil end
    return c and found and found.listen=='0.0.0.0' and tonumber(found.port)==c.port and
        found.protocol=='shadowsocks' and found.settings and found.settings.method==c.method and
        found.settings.password==c.password and found.settings.network==c.network or false
end
function M.guard(c)
    local s={'destroy table inet cudy_ss_zt','table inet cudy_ss_zt {'}
    if c then
        local endpoint='ip daddr '..c.listen..' meta l4proto { tcp, udp } th dport '..c.port
        local selected='ip daddr '..c.listen..' meta l4proto '..transport(c.network)..' th dport '..c.port
        s[#s+1]='chain scope { type filter hook prerouting priority -310; policy accept;'
        s[#s+1]=endpoint..' iifname != "'..c.interface..'" counter drop'
        s[#s+1]=endpoint..' ip saddr != '..c.subnet..' counter drop'
        if c.network~='tcp,udp' then
            local unselected=c.network=='tcp' and 'udp' or 'tcp'
            s[#s+1]='ip daddr '..c.listen..' meta l4proto '..unselected..' th dport '..c.port..' counter drop'
        end
        s[#s+1]='}'
        s[#s+1]='chain ingress { type nat hook prerouting priority -110; policy accept;'
        s[#s+1]=selected..' iifname "'..c.interface..'" ip saddr '..c.subnet..' dnat ip to '..M.peer..':'..c.port
        s[#s+1]='}'
    end
    -- Only the authorized encrypted SS endpoint may enter the namespace.
    -- Return traffic from connections initiated inside it is accepted first.
    s[#s+1]='chain restrict_peer { type filter hook forward priority -15; policy accept;'
    s[#s+1]='ip daddr '..M.peer..' ct direction reply ct state established,related return'
    if c then
        s[#s+1]='ip daddr '..M.peer..' iifname "'..c.interface..'" ip saddr '..c.subnet..
            ' meta l4proto '..transport(c.network)..' th dport '..c.port..' return'
    end
    s[#s+1]='ip daddr '..M.peer..' counter drop'
    s[#s+1]='}'
    s[#s+1]='chain source_nat { type nat hook postrouting priority 90; policy accept;'
    s[#s+1]='ip saddr '..M.peer..' ct direction original oifname != "css-host" masquerade'
    s[#s+1]='}'
    s[#s+1]='}'
    return table.concat(s,'\n')..'\n'
end
function M.bridge(old,new)
    -- A temporary restriction remains active across the transaction and rollback.
    local s={'destroy table inet cudy_ss_retired','table inet cudy_ss_retired {',
        'chain scope { type filter hook prerouting priority -311; policy accept;'}
    local scopes={[1]=old,[2]=new}
    for i=1,2 do
        local c=scopes[i]
        if c then
            local e='ip daddr '..c.listen..' meta l4proto { tcp, udp } th dport '..c.port
            s[#s+1]=e..' iifname != "'..c.interface..'" counter drop'
            s[#s+1]=e..' ip saddr != '..c.subnet..' counter drop'
        end
    end
    s[#s+1]='}'
    s[#s+1]='}'
    return table.concat(s,'\n')..'\n'
end
return M

