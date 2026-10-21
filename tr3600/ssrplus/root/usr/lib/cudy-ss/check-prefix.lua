local function ip(s)
    local a,b,c,d=s:match('^(%d+)%.(%d+)%.(%d+)%.(%d+)$')
    if not a then return end
    local n=0
    for _,v in ipairs({a,b,c,d}) do v=tonumber(v); if v>255 then return end; n=n*256+v end
    return n
end
local wanted=assert(ip('198.18.255.0'))
local pipe=assert(io.popen('ip -4 route show table all'))
for line in pipe:lines() do
    local addr,bits=line:match('^%S+%s+(%d+%.%d+%.%d+%.%d+)/(%d+)')
    if not addr then addr,bits=line:match('^(%d+%.%d+%.%d+%.%d+)/(%d+)') end
    if not addr then addr=line:match('^local%s+(%d+%.%d+%.%d+%.%d+)'); bits=addr and '32' end
    if addr then
        local n,p=ip(addr),tonumber(bits)
        if n and p and p>0 and p<=32 then
            local width=2^(32-p);local first=math.floor(n/width)*width
            assert(first>wanted+3 or first+width-1<wanted,'198.18.255.0/30 conflicts with an existing route')
        end
    end
end
pipe:close()

