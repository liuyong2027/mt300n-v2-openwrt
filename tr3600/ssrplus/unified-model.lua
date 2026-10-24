-- Appended to the shared SS model by unify-ss.py. All SS entries share the
-- same isolated client interface, while their original access scopes remain.
M.host='198.18.255.1'
M.peer='198.18.255.2'
local host_rules=M.rules
function M.namespace_config(rows)
    local config={log={loglevel='warning'},dns={queryStrategy='UseIPv4',servers={M.host}},
        inbounds={},outbounds={{tag='direct',protocol='freedom',settings={domainStrategy='UseIPv4'}}}}
    local ports={}
    for _,raw in ipairs(rows) do
        if raw.enable=='1' and raw.type=='shadowsocks' then
            local c=M.normalize(raw)
            assert(type(c.id)=='string' and c.id:match('^[%w_]+$'),'Invalid SS section')
            assert(not ports[c.port],'Enabled server port collision');ports[c.port]=true
            config.inbounds[#config.inbounds+1]={tag='ssr-server-'..c.id,listen='0.0.0.0',
                port=c.port,protocol='shadowsocks',settings={method=c.method,password=c.password,network=c.network},
                sniffing={enabled=true,destOverride={'http','tls'},routeOnly=true}}
        end
    end
    return config
end
function M.same(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~='table' then return a==b end
    for k,v in pairs(a) do if not M.same(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end
    return true
end
local function permits(c,lan,local_output)
    local list={}
    for protocol in c.network:gmatch('[^,]+') do
        local endpoint='meta nfproto ipv4 '..protocol..' dport '..c.port
        if local_output then
            if c.scope=='loopback' then list[#list+1]='ip daddr 127.0.0.1 '..endpoint
            else list[#list+1]='fib daddr type local '..endpoint end
        elseif c.scope=='public' then
            list[#list+1]='fib daddr type local '..endpoint
        elseif c.scope=='lan' and type(lan)=='table' and type(lan.device)=='string' and
            lan.device:match('^[%w_.:-]+$') and #lan.device<=15 then
            for _,address in ipairs(lan.addresses or {}) do
                assert(M.ipv4(address),'Invalid LAN IPv4 address')
                list[#list+1]='iifname "'..lan.device..'" ip daddr '..address..' '..endpoint
            end
        end
    end
    return list
end
function M.rules(rows,lan,active)
    local ordinary,servers,ports={},{},{}
    for _,raw in ipairs(rows) do
        if raw.enable=='1' then
            local c=M.normalize(raw)
            assert(not ports[c.port],'Enabled server port collision');ports[c.port]=true
            if raw.type=='shadowsocks' then servers[#servers+1]={raw=raw,c=c}
            else ordinary[#ordinary+1]=raw end
        end
    end
    local s={host_rules(ordinary,lan,active),'destroy table inet cudy_ssr_ss','table inet cudy_ssr_ss {',
        'chain ingress_guard { type filter hook prerouting priority -190; policy accept;',
        'iifname "css-host" ct direction reply return'}
    for _,entry in ipairs(servers) do
        local c=entry.c
        if active==nil or active[c.id] then
            for _,match in ipairs(permits(c,lan,false)) do s[#s+1]=match..' return' end
            s[#s+1]='fib daddr type local meta l4proto { tcp, udp } th dport '..c.port..' counter drop'
        end
    end
    s[#s+1]='}'
    s[#s+1]='chain local_guard { type filter hook output priority -190; policy accept;'
    for _,entry in ipairs(servers) do
        local c=entry.c
        if active==nil or active[c.id] then
            for _,match in ipairs(permits(c,lan,true)) do s[#s+1]=match..' return' end
            s[#s+1]='fib daddr type local meta l4proto { tcp, udp } th dport '..c.port..' counter drop'
        end
    end
    s[#s+1]='}'
    s[#s+1]='chain ingress { type nat hook prerouting priority -180; policy accept;'
    for _,entry in ipairs(servers) do
        local c=entry.c
        if active==nil or active[c.id] then
            for _,match in ipairs(permits(c,lan,false)) do s[#s+1]=match..' dnat ip to '..M.peer..':'..c.port end
        end
    end
    s[#s+1]='}';s[#s+1]='chain local_ingress { type nat hook output priority -180; policy accept;'
    for _,entry in ipairs(servers) do
        local c=entry.c
        if active==nil or active[c.id] then
            for _,match in ipairs(permits(c,lan,true)) do s[#s+1]=match..' dnat ip to '..M.peer..':'..c.port end
        end
    end
    s[#s+1]='}';s[#s+1]='chain protect_peer { type filter hook forward priority -15; policy accept;'
    s[#s+1]='ip daddr '..M.peer..' ct direction reply ct state established,related return'
    for _,entry in ipairs(servers) do
        local c=entry.c
        if active==nil or active[c.id] then for protocol in c.network:gmatch('[^,]+') do
            s[#s+1]='ip daddr '..M.peer..' ct status dnat '..protocol..' dport '..c.port..' return'
        end end
    end
    s[#s+1]='ip daddr '..M.peer..' counter drop';s[#s+1]='}'
    s[#s+1]='chain source_nat { type nat hook postrouting priority 90; policy accept;'
    s[#s+1]='oifname "css-host" ip saddr 127.0.0.0/8 ip daddr '..M.peer..' masquerade'
    s[#s+1]='ip saddr '..M.peer..' ct direction original oifname != "css-host" masquerade'
    s[#s+1]='}';s[#s+1]='}'
    s[#s+1]='flush chain inet fw4 CUDY_SSR_SS_FORWARD'
    for _,entry in ipairs(servers) do
        local c=entry.c
        if active==nil or active[c.id] then for protocol in c.network:gmatch('[^,]+') do
            s[#s+1]='add rule inet fw4 CUDY_SSR_SS_FORWARD oifname "css-host" ip daddr '..M.peer..
                ' ct status dnat '..protocol..' dport '..c.port..' accept'
        end end
    end
    return table.concat(s,'\n')..'\n'
end
