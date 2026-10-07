local M=dofile(arg[1])
local count=0
local function test(name,fn) fn(); count=count+1; print('PASS '..name) end
local function raw()
 return {enabled='1',listen='192.168.7.6',subnet='192.168.7.0/24',interface='ztfixture01',network_id='0123456789abcdef',port='8388',method='aes-128-gcm',password=string.rep('x',32)}
end
local function config() return {inbounds={{tag='local-test',port=10808}},outbounds={{tag='direct'},{tag='proxy'}},routing={rules={{outboundTag='proxy'}}},dns={servers={'1.1.1.1'}}} end
test('disabled feature does not require credentials',function() assert(not M.validate({enabled='0'})) end)
test('valid private SS configuration',function() assert(M.validate(raw()).port==8388) end)
for _,v in ipairs({'0.0.0.0','114.246.103.22','192.168.8.6','192.168.7.0','192.168.7.255','192.168.007.6'}) do
 test('reject invalid or unscoped listener '..v,function() local r=raw(); r.listen=v; assert(not pcall(M.validate,r)) end)
end
test('reject wrong subnet interface port cipher and short secret',function()
 for k,v in pairs({subnet='192.168.7.0/16',interface='zt0";bad',port='10808',method='none',password='short'}) do local r=raw(); r[k]=v; assert(not pcall(M.validate,r)) end
end)
test('private authorized matching ZeroTier network required',function()
 local c=M.validate(raw()); local n={{id=c.network_id,type='PRIVATE',status='OK',portDeviceName=c.interface,assignedAddresses={c.listen..'/24'}}}
 assert(M.available(c,n)); n[1].type='PUBLIC'; assert(not M.available(c,n)); n[1].type='PRIVATE'; n[1].status='ACCESS_DENIED'; assert(not M.available(c,n))
 n[1].status='OK'; n[1].assignedAddresses={'192.168.8.6/24'}; assert(not M.available(c,n))
end)
test('augment preserves all original routing dns and outbounds',function()
 local c=M.validate(raw()); local b=config(); local routes,dns,out=b.routing,b.dns,b.outbounds
 M.augment(b,c,true); assert(#b.inbounds==2 and b.routing==routes and b.dns==dns and b.outbounds==out)
 local s=b.inbounds[2]; assert(s.tag==M.tag and s.listen==c.listen and s.settings.method=='aes-128-gcm' and s.settings.network=='tcp,udp')
end)
test('unavailable interface omits SS and preserves normal proxy',function() local b=config(); assert(#M.augment(b,M.validate(raw()),false).inbounds==1) end)
test('reject port and duplicate tag conflicts',function()
 local b=config(); b.inbounds[1].port=8388; assert(not pcall(M.augment,b,M.validate(raw()),true))
 b=config(); b.inbounds[1].tag=M.tag; assert(not pcall(M.augment,b,M.validate(raw()),true))
end)
test('guard rejects non-ZeroTier input and unapproved subnet for both transports',function()
 local g=M.guard(M.validate(raw())); assert(g:find('iifname != "ztfixture01"',1,true) and g:find('ip saddr != 192.168.7.0/24',1,true))
 assert(g:find('meta l4proto { tcp, udp } th dport 8388',1,true) and g:find('priority -15',1,true))
end)
print('SS ZeroTier configuration/scope/integration: '..count..' tests passed')
