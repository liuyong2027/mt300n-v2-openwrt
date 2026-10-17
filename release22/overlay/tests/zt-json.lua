local j=dofile('package/luci-app-mango-proxy/root/usr/lib/mango/zt-json.lua')
local value=j.decode('{"settings":{"primaryPort":9993,"secondaryPort":48170,"tertiaryPort":20089,"portMappingEnabled":true},"label":"\\u4e2d\\u6587","false":false,"null":null}')
assert(value.settings.secondaryPort==48170 and value.settings.portMappingEnabled==true)
assert(value['false']==false and value['null']==nil)
assert(#value.label==6)
local listing=j.decode('{"nftables":[{"table":{"family":"inet","name":"fw4"}},{"rule":{"handle":77,"expr":[{"jump":{"target":"mango_zt_direct"}}]}}]}')
assert(listing.nftables[2].rule.expr[1].jump.target=='mango_zt_direct')
assert(j.decode(j.encode(value)).settings.tertiaryPort==20089)
for _,bad in ipairs({'{','{"x":true trailing}', '{"x":"\\q"}', '[1,]','null garbage'}) do
    assert(not pcall(j.decode,bad),bad)
end
print('Self-contained JSON: config, nft structure, booleans, Unicode and malformed input passed')
