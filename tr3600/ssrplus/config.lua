-- The namespace makes decrypted SS traffic enter the one SSR Plus+ policy.
local M={}
M.network='198.18.255.0/30'
M.host='198.18.255.1'
M.peer='198.18.255.2'
function M.config(c)
    return {
        log={loglevel='warning'},
        dns={queryStrategy='UseIPv4',servers={M.host}},
        inbounds={{tag='cudy-ss-zt',listen='0.0.0.0',port=c.port,protocol='shadowsocks',
            settings={method=c.method,password=c.password,network='tcp,udp'},
            sniffing={enabled=true,destOverride={'http','tls'},routeOnly=true}}},
        outbounds={{tag='direct',protocol='freedom',settings={domainStrategy='UseIPv4'}}}
    }
end
function M.guard(c)
    local s={'destroy table inet cudy_ss_zt','table inet cudy_ss_zt {'}
    if c then
        local endpoint='ip daddr '..c.listen..' meta l4proto { tcp, udp } th dport '..c.port
        s[#s+1]='chain scope { type filter hook prerouting priority -310; policy accept;'
        s[#s+1]=endpoint..' iifname != "'..c.interface..'" counter drop'
        s[#s+1]=endpoint..' ip saddr != '..c.subnet..' counter drop'
        s[#s+1]='}'
        s[#s+1]='chain ingress { type nat hook prerouting priority -110; policy accept;'
        s[#s+1]=endpoint..' iifname "'..c.interface..'" ip saddr '..c.subnet..' dnat ip to '..M.peer..':'..c.port
        s[#s+1]='}'
    end
    -- Only the authorized encrypted SS endpoint may enter the namespace.
    -- Return traffic from connections initiated inside it is accepted first.
    s[#s+1]='chain restrict_peer { type filter hook forward priority -15; policy accept;'
    s[#s+1]='ip daddr '..M.peer..' ct state established,related return'
    if c then
        s[#s+1]='ip daddr '..M.peer..' iifname "'..c.interface..'" ip saddr '..c.subnet..
            ' meta l4proto { tcp, udp } th dport '..c.port..' return'
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

