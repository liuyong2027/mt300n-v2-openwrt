-- Exercise the actual runner with private UCI/ubus/nft fixtures. No shell runs.
local m=dofile('package/luci-app-mango-proxy/root/usr/lib/mango/zt-direct.lua')
local runner='package/luci-app-mango-proxy/root/usr/libexec/mango-zt-direct-run'
local old_popen,old_exit,old_arg=io.popen,os.exit,arg
local config,conf,listing,status,writes,board
package.preload['nixio.fs']=function() return {readfile=function(path)
    if path=='/tmp/sysinfo/board_name' then return board end
    if path=='/owner/custom.json' then return 'CONF' end
end} end
package.preload['luci.jsonc']=function() return {parse=function(text)
    if text=='CONF' then return conf end
    if text=='STATUS' then return status end
    if text=='LIST' then return listing end
end} end
package.preload['uci']=function() return {cursor=function() return {get=function(self,c,s,o)
    return config[c..'.'..s..(o and '.'..o or '')]
end} end} end
package.preload['mango.zt-direct']=function() return m end
local function run(changes,stop)
    board='glinet,gl-mt300n-v2\n'
    config={['zerotier.global.enabled']='1',['zerotier.global.local_conf_path']='/owner/custom.json',
        ['firewall.mango_zt_direct']='include',['firewall.mango_zt_direct.path']='/usr/libexec/mango-zt-direct'}
    for k,v in pairs(changes or {}) do config[k]=v end
    conf={settings={secondaryPort=48170,tertiaryPort=20089,portMappingEnabled=true}}
    status={up=true,route={{target='0.0.0.0',mask=0,nexthop='10.20.30.1'}}}
    listing={nftables={{table={family='inet',name='fw4'}},{chain={family='inet',table='fw4',name='input_wan'}},
        {chain={family='inet',table='fw4',name=m.chain,comment=m.owner}},
        {rule={family='inet',table='fw4',chain='input_wan',comment=m.owner,handle=77,expr={{jump={target=m.chain}}}}}}}
    writes={}
    io.popen=function(cmd,mode)
        if mode=='w' then
            assert(cmd=='nft -f -')
            return {write=function(self,text) writes[#writes+1]=text end,close=function() return true end}
        end
        local result=cmd:find('ubus',1,true) and 'STATUS' or 'LIST'
        assert(cmd:find('ubus',1,true) or cmd:find('nft -j',1,true))
        return {read=function() return result end,close=function() return true end}
    end
    os.exit=function(code) error({exit_code=code}) end
    arg=stop and {'stop'} or {}
    local ok,err=pcall(assert(loadfile(runner)))
    assert(ok or type(err)=='table' and err.exit_code==0,err)
    assert(#writes==1)
    return writes[1]
end
local text=run()
assert(text:find('comment "ZeroTier direct UDP"',1,true))
assert(text:find('comment "ZeroTier UPnP discovery"',1,true))
for _,test in ipairs({{{},true},{{['zerotier.global.enabled']='0'}},{{['firewall.mango_zt_direct.enabled']='0'}},
    {{['firewall.mango_zt_direct']='rule'}},{{['firewall.mango_zt_direct.path']='/owner/other'}}}) do
    text=run(test[1],test[2])
    assert(text:find('delete chain inet fw4 '..m.chain,1,true))
    assert(not text:find(' accept',1,true))
end
io.popen,os.exit,arg=old_popen,old_exit,old_arg
print('ZeroTier runner: enabled, explicit stop, disabled client/include and include ownership passed')
