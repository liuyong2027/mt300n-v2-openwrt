local m=dofile('package/luci-app-mango-proxy/root/usr/lib/mango/zt-direct.lua')
local conf={settings={secondaryPort=48170,tertiaryPort=20089,portMappingEnabled=true}}
local status={up=true,route={{target='0.0.0.0',mask=0,nexthop='10.20.30.1'}}}
local p=assert(m.policy(true,nil,conf,status)); assert(p.gateway=='10.20.30.1' and p.ports[1]==9993)
assert(#m.policy(false,nil,nil,nil).ports==0)
assert(not m.policy(true,443,conf,status))
assert(not m.policy(true,48170,conf,status))
assert(not m.policy(true,nil,{},status))
assert(not m.policy(true,nil,{settings={secondaryPort=48170,tertiaryPort='9; accept'}},status))
assert(not m.policy(true,nil,conf,{up=false}).gateway)
assert(not m.policy(true,nil,conf,{up=true,route={{target='0.0.0.0',mask=0,nexthop='10.1.1.1;accept'}}}).gateway)
conf.settings.portMappingEnabled=false
assert(not m.policy(true,nil,conf,status).gateway)
conf.settings.portMappingEnabled=true
local listing={nftables={{table={family='inet',name='fw4'}},{chain={family='inet',table='fw4',name='input_wan'}}}}
local text=assert(m.transaction(p,listing))
assert(text:find('udp dport { 9993, 48170, 20089 } accept',1,true))
assert(text:find('ip saddr 10.20.30.1 udp sport 1900 udp dport 1024-65535 accept',1,true))
assert(not text:find('flush ruleset',1,true))
listing.nftables[#listing.nftables+1]={chain={family='inet',table='fw4',name=m.chain,comment='someone-else'}}
assert(not m.transaction(p,listing))
listing.nftables[#listing.nftables].chain.comment=m.owner
listing.nftables[#listing.nftables+1]={rule={family='inet',table='fw4',chain='input_wan',comment=m.owner,handle=77,expr={{jump={target=m.chain}}}}}
text=assert(m.transaction({ports={}},listing))
assert(text:find('delete rule inet fw4 input_wan handle 77',1,true))
assert(text:find('delete chain inet fw4 '..m.chain,1,true))
assert(not text:find(' accept',1,true))
listing.nftables[#listing.nftables].rule.expr={{jump={target='other'}}}
assert(not m.transaction(p,listing))
assert(not m.transaction(p,{nftables={}}))
print('ZeroTier direct policy: enabled/disabled, custom ports, dynamic gateway, injection and ownership guards passed')
