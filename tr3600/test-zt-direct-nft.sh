#!/bin/sh
# Run in an isolated Linux network namespace; never modify the runner's firewall.
set -eu
nft add table inet fw4
nft 'add chain inet fw4 input_wan { type filter hook input priority 0; policy accept; }'
lua5.1 - <<'LUA' | nft -f -
local m=dofile('tr3600/network-root/usr/lib/lua/cudy/zt-direct.lua')
print(assert(m.transaction({ports={9993,48170,20089},gateway='10.20.30.1'}, {nftables={{table={family='inet',name='fw4'}},{chain={family='inet',table='fw4',name='input_wan'}}}})))
LUA
nft -j list table inet fw4 > /tmp/cudy-zt-direct-list.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/cudy-zt-direct-list.json'))['nftables']
assert any(x.get('chain',{}).get('comment')=='cudy-zt-direct-v1' for x in d)
assert len([x for x in d if x.get('rule',{}).get('chain')=='cudy_zt_direct'])==2
PY
lua5.1 - <<'LUA' | nft -f -
local m=dofile('tr3600/network-root/usr/lib/lua/cudy/zt-direct.lua')
-- Handles were allocated in order in this new isolated namespace.
-- Read actual handles rather than depending on allocation order.
local p=io.popen('nft -a list chain inet fw4 input_wan','r')
local s=p:read('*a');p:close()
local h=assert(tonumber(s:match('comment "cudy%-zt%-direct%-v1" # handle (%d+)')))
print(assert(m.transaction({ports={}}, {nftables={{table={family='inet',name='fw4'}},{chain={family='inet',table='fw4',name='input_wan'}},{chain={family='inet',table='fw4',name=m.chain,comment=m.owner}},{rule={family='inet',table='fw4',chain='input_wan',comment=m.owner,handle=h,expr={{jump={target=m.chain}}}}}})))
LUA
if nft list chain inet fw4 cudy_zt_direct 2>/dev/null; then exit 1; fi
printf '%s\n' 'ZeroTier nft transaction and owned cleanup passed'
