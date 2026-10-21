-- MIT. Pure conversion of the existing Mango UCI model; no I/O or shell execution.
local M = {}
local function values(v)
    if type(v)=='table' then return v end
    local r={}; for item in tostring(v or ''):gmatch('%S+') do r[#r+1]=item end
    return r
end
local function scalar(v)
    v=tostring(v or '')
    assert(not v:find('[%z\r\n]'),'Multiline or NUL configuration value')
    return v
end
local function quote(v)
    return "'"..scalar(v):gsub("'", "'\\''").."'"
end
function M.encode(sections)
    local out={}
    for _,s in ipairs(sections) do
        assert(s.name:match('^[%w_]+$') and s.type:match('^[%w_]+$'),'Invalid section name')
        out[#out+1]='config '..s.type..' '..quote(s.name)
        local keys={}; for key in pairs(s.options) do keys[#keys+1]=key end; table.sort(keys)
        for _,key in ipairs(keys) do
            assert(key:match('^[%w_]+$'),'Invalid option name')
            local v=s.options[key]
            if type(v)=='table' then
                for _,item in ipairs(v) do out[#out+1]='\tlist '..key..' '..quote(item) end
            elseif v~=nil then out[#out+1]='\toption '..key..' '..quote(v) end
        end
        out[#out+1]=''
    end
    return table.concat(out,'\n')..'\n'
end
function M.node(n)
    local protocol=n.protocol or 'vless'
    assert(protocol=='vless' or protocol=='vmess' or protocol=='shadowsocks','Unsupported legacy protocol')
    local o={type='v2ray',v2ray_protocol=protocol,alias=n.label or n['.name'],
        server=n.address,server_port=n.port,local_port='12345',switch_enable='0',
        transport='raw',insecure='0',fast_open='0'}
    assert(o.server and o.server_port,'Incomplete node')
    if protocol=='shadowsocks' then
        o.encrypt_method_ss=n.method; o.password=n.password
        assert(o.encrypt_method_ss and o.password,'Missing Shadowsocks credentials')
    else
        assert(n.uuid,'Missing UUID')
        o.vmess_id=n.uuid
        if protocol=='vless' then
            o.reality='1'; o.tls='0'; o.tls_host=n.sni
            o.reality_publickey=n.public_key; o.reality_shortid=n.short_id or ''
            o.reality_spiderx=n.spider_x or '/'; o.fingerprint=n.fingerprint or 'chrome'
            o.tls_flow='xtls-rprx-vision'; o.vless_encryption='none'
            assert(o.tls_host and o.reality_publickey,'Incomplete REALITY node')
        else
            o.transport=n.network or 'raw'; o.security=n.vmess_security or 'auto'
            o.alter_id=n.alter_id or '0'; o.tls=n.tls=='tls' and '1' or '0'
            o.tls_host=n.sni or n.address
            if o.transport=='ws' then o.ws_host=n.ws_host or ''; o.ws_path=n.ws_path or '/' end
        end
    end
    return o
end
function M.plan(policy,nodes)
    local mode=policy.mode or 'direct'
    assert(({direct=true,split=true,global=true,gfw=true})[mode],'Unknown legacy policy mode')
    local ids,byid={},{}
    for _,n in ipairs(nodes) do
        local id=assert(n['.name'])
        assert(id:match('^[%w_]+$') and not byid[id],'Invalid or duplicated legacy node ID')
        ids[#ids+1]=id; byid[id]=n
    end
    local selected=policy.node or ''
    if mode~='direct' then assert(byid[selected],'Configured main node is missing') end
    local g={global_server=mode=='direct' and 'nil' or selected,udp_relay_server='same',
        netflix_server='nil',netflix_enable='0',threads='1',
        run_mode=({split='router',global='all',gfw='gfw',direct='router'})[mode],
        dports='2',pdnsd_enable='1',prefer_nft='1',tunnel_forward='1.1.1.1:53',
        monitor_enable='1',enable_switch=policy.failover=='1' and '1' or '0',
        switch_time='60',switch_timeout='5',switch_try_count='3',shunt_dns='0',
        chinadns_forward='none',mango_migrated='1',mango_mode=mode,
        mango_direct_socks=mode=='direct' and policy.socks_server=='1' and '1' or '0'}
    local subscribe={proxy='0',auto_update='0',ss_type='v2ray',filter_words='',
        user_agent='v2rayN/9.99',url_test_url='https://www.google.com/generate_204'}
    if policy.subscription_url and policy.subscription_url~='' then
        subscribe.subscribe_url={policy.subscription_url}
    end
    local access={lan_ac_mode='0',router_proxy='1',Interface={'lan','zt+'},
        wan_bp_ips=values(policy.bypass4)}
    local socks={server='same',enabled=mode=='direct' and '0' or '1',local_port=policy.socks_server=='1' and (policy.socks_port or '10810') or '10808',
        socks5_auth='noauth',mango_expose=policy.socks_server=='1' and '1' or '0'}
    local out={{type='global',name='global',options=g},
        {type='server_subscribe',name='subscribe',options=subscribe},
        {type='access_control',name='access',options=access},
        {type='socks5_proxy',name='socks',options=socks},
        {type='server_global',name='server',options={enable_server='0'}},
        {type='global_xray_fragment',name='fragment',options={fragment='0',noise='0'}}}
    local order,seen={},{}
    local function add(id)
        if byid[id] and not seen[id] then order[#order+1]=id;seen[id]=true end
    end
    add(selected)
    local backups={}
    for _,id in ipairs(values(policy.backup_nodes)) do
        assert(byid[id],'Configured backup node is missing')
        backups[id]=true; add(id)
    end
    for _,id in ipairs(ids) do add(id) end
    for _,id in ipairs(order) do
        local o=M.node(byid[id])
        if id==selected or backups[id] then o.switch_enable='1' end
        out[#out+1]={type='servers',name=id,options=o}
    end
    local white={}
    for _,d in ipairs(values(policy.direct_domains)) do
        assert(d:match('^[%w][%w%.%-]*$') and not d:find('..',1,true),'Invalid direct domain')
        white[#white+1]=d:lower()
    end
    return {sections=out,white=white,mode=mode,node_count=#nodes,
        old_config_retained=true,legacy_lan_device=policy.lan_device or 'br-lan'}
end
return M
