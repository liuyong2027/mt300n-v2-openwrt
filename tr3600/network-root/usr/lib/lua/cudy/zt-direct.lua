-- Narrow ZeroTier UDP/SSDP policy. No network IDs or upstream addresses baked in.
local M = {}
M.owner = 'cudy-zt-direct-v1'
M.chain = 'cudy_zt_direct'
local function port(v)
    local n = tonumber(v)
    if n and n == math.floor(n) and n >= 1024 and n <= 65535 then return n end
end
function M.ipv4(v)
    if type(v) ~= 'string' then return end
    local a,b,c,d = v:match('^(%d+)%.(%d+)%.(%d+)%.(%d+)$')
    if not a then return end
    a,b,c,d = tonumber(a),tonumber(b),tonumber(c),tonumber(d)
    if a < 1 or a >= 224 or a == 127 or b > 255 or c > 255 or d > 255 then return end
    return string.format('%d.%d.%d.%d',a,b,c,d)
end
function M.policy(enabled, primary, conf, status)
    if not enabled then return {ports={}} end
    local s = type(conf)=='table' and conf.settings
    if type(s)~='table' then return nil,'Missing local.conf settings; no UDP ports opened' end
    local p = port(primary or s.primaryPort or 9993)
    local q,r = port(s.secondaryPort),port(s.tertiaryPort)
    if not p or not q or not r or p==q or q==r or p==r then
        return nil,'Invalid or non-fixed ZeroTier ports; no UDP ports opened'
    end
    local result={ports={p,q,r}}
    if s.portMappingEnabled ~= true then return result end
    if type(status)~='table' or status.up~=true then return result end
    for _,route in ipairs(status.route or {}) do
        if route.target=='0.0.0.0' and tonumber(route.mask)==0 then
            result.gateway=M.ipv4(route.nexthop)
            if result.gateway then break end
        end
    end
    return result
end
function M.transaction(policy, listing)
    local found,chain,wan,jumps=false,false,false,{}
    for _,entry in ipairs(listing.nftables or {}) do
        local t=entry.table
        if t and t.family=='inet' and t.name=='fw4' then found=true end
        local c=entry.chain
        if c and c.family=='inet' and c.table=='fw4' then
            if c.name=='input_wan' then wan=true end
            if c.name==M.chain then
                if c.comment~=M.owner then return nil,'Unowned nft chain; left unchanged' end
                chain=true
            end
        end
        local r=entry.rule
        if r and r.family=='inet' and r.table=='fw4' and r.chain=='input_wan' and r.comment==M.owner then
            local owned=false
            for _,expr in ipairs(r.expr or {}) do
                if expr.jump and expr.jump.target==M.chain then owned=true end
            end
            if not owned or type(r.handle)~='number' or r.handle~=math.floor(r.handle) then
                return nil,'Unowned nft jump; left unchanged'
            end
            jumps[#jumps+1]=r.handle
        end
    end
    if not found or not wan then return nil,'fw4 input_wan is not ready' end
    local lines={}
    for _,h in ipairs(jumps) do lines[#lines+1]='delete rule inet fw4 input_wan handle '..h end
    if chain then lines[#lines+1]='flush chain inet fw4 '..M.chain end
    if #policy.ports==0 then
        if chain then lines[#lines+1]='delete chain inet fw4 '..M.chain end
        return table.concat(lines,'\n')..'\n'
    end
    if not chain then lines[#lines+1]='add chain inet fw4 '..M.chain..' { comment "'..M.owner..'"; }' end
    lines[#lines+1]='add rule inet fw4 '..M.chain..' udp dport { '..table.concat(policy.ports,', ')..' } accept'
    if policy.gateway then
        lines[#lines+1]='add rule inet fw4 '..M.chain..' ip saddr '..policy.gateway..' udp sport 1900 udp dport 1024-65535 accept'
    end
    lines[#lines+1]='insert rule inet fw4 input_wan jump '..M.chain..' comment "'..M.owner..'"'
    return table.concat(lines,'\n')..'\n'
end
return M
