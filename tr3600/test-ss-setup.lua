local M=dofile(arg[1])
local fixture={enabled='0',port='8388',method='aes-128-gcm'}
local network={id='0123456789abcdef',type='PRIVATE',status='OK',portDeviceName='ztfixture01',assignedAddresses={'192.168.77.6/24'}}
local request={enabled=true,port=8388,method='aes-128-gcm',password=string.rep('K',32)}
local selected=M.select(fixture,{network})
assert(selected.listen=='192.168.77.6' and selected.subnet=='192.168.77.0/24' and not fixture.listen)
assert(M.request(fixture,request,{network}).enabled=='1')
assert(M.request(fixture,{enabled=false,port=8388,method='aes-128-gcm',password=''}).enabled=='0')
for _,kind in ipairs({'PUBLIC','ACCESS_DENIED','ambiguous','wrong-prefix','non-private'}) do
 local n={};for k,v in pairs(network) do n[k]=v end
 local networks={n}
 if kind=='PUBLIC' then n.type='PUBLIC'
 elseif kind=='ACCESS_DENIED' then n.status='ACCESS_DENIED'
 elseif kind=='ambiguous' then networks[2]=network
 elseif kind=='wrong-prefix' then n.assignedAddresses={'192.168.77.6/16'}
 else n.assignedAddresses={'114.1.2.3/24'} end
 assert(not M.select(fixture,networks).listen,kind)
 assert(not pcall(M.request,fixture,request,networks),kind)
end
local remembered=M.request(fixture,request,{network})
network.assignedAddresses={'192.168.88.6/24'}
assert(M.select(remembered,{network}).listen=='192.168.77.6','Never silently move an existing authorization')
assert(not M.available(M.validate(remembered),{network}))
print('PASS disabled/no-credential default, explicit private-network bootstrap, ambiguity/public refusal and immutable remembered scope')
