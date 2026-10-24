-- The user requested deletion, not migration, of the dedicated private SS.
local M={}
function M.run(u,fs)
    u=u or require('uci').cursor();fs=fs or require('nixio.fs')
    local network=u:get('network','cudy_ss')
    assert(not network or (network=='interface' and u:get('network','cudy_ss','device')=='css-host'),
        'Ordinary SS network section name collision')
    u:foreach('firewall','zone',function(s)
        assert(s.name~='ssrservers' or s['.name']=='ssr_ss','Ordinary SS zone name collision')
    end)
    -- Refuse collisions with unrelated owner sections before any mutation.
    for id,kind in pairs({ssr_ss='zone',ssr_ss_gate='include',ssr_ss_to_wan='forwarding',
        ssr_ss_to_lan='forwarding',ssr_ss_to_mangozt='forwarding'}) do
        local existing=u:get('firewall',id)
        assert(not existing or (existing==kind and u:get('firewall',id,'cudy_owner')=='ssr-ss-v4'),
            'Ordinary SS firewall section name collision')
    end
    local remove={}
    u:foreach('shadowsocksr','server_config',function(s)
        if s['.name']=='cudy_zt_private' or s.cudy_private=='1' or s.cudy_access=='zerotier' then
            remove[#remove+1]=s['.name']
        end
    end)
    for _,id in ipairs(remove) do assert(u:delete('shadowsocksr',id)) end
    assert(u:commit('shadowsocksr'))
    -- These names were created by the old private runtime. Other firewall
    -- sections, ZeroTier UDP/SSDP helpers and owner network settings remain.
    for _,id in ipairs({'cudy_ss_guard','cudy_ss_route_guard','cudy_ss',
        'cudy_ss_to_wan','cudy_ss_to_lan','cudy_ss_to_zt','cudy_zt_to_ss','cudy_zt_ipv6_guard'}) do
        u:delete('firewall',id)
    end
    assert(u:set('network','cudy_ss','interface'))
    assert(u:set('network','cudy_ss','proto','none'))
    assert(u:set('network','cudy_ss','device','css-host'))
    assert(u:commit('network'))
    assert(u:set('firewall','ssr_ss','zone'))
    for k,v in pairs({name='ssrservers',input='ACCEPT',output='ACCEPT',forward='REJECT',device={'css-host'},cudy_owner='ssr-ss-v4'}) do
        assert(u:set('firewall','ssr_ss',k,v))
    end
    local zones={};u:foreach('firewall','zone',function(s)zones[s.name]=true end)
    for _,dest in ipairs({'wan','lan','mangozt'}) do
        if zones[dest] then
            local id='ssr_ss_to_'..dest
            assert(u:set('firewall',id,'forwarding'))
            assert(u:set('firewall',id,'src','ssrservers'))
            assert(u:set('firewall',id,'dest',dest))
            assert(u:set('firewall',id,'cudy_owner','ssr-ss-v4'))
        end
    end
    assert(u:set('firewall','ssr_ss_gate','include'))
    for k,v in pairs({enabled='1',type='nftables',position='ruleset-pre',path='/etc/cudy-ss/route-guard.nft',cudy_owner='ssr-ss-v4'}) do
        assert(u:set('firewall','ssr_ss_gate',k,v))
    end
    assert(u:commit('firewall'))
    for _,path in ipairs({'/etc/config/cudy_ss','/etc/cudy-ss/guard.nft',
        '/etc/cudy-ssrplus/cudy_ss.before-migration','/etc/cudy-ssrplus/cudy_ss.before-server-v2',
        '/etc/cudy-ssrplus/ss-server-v2.done'}) do
        if fs.access(path) then assert(fs.remove(path)) end
    end
    return #remove
end
return M
