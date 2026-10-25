-- Native runtime only; credentials never appear in diagnostics or command lines.
local fs=require('nixio.fs')
local json=require('luci.jsonc')
local model=require('cudy.ssr-server')
local M={}
local function capture(command)
    local p=io.popen(command,'r');if not p then return '' end
    local data=p:read('*a');p:close();return data
end
function M.rows(u)
    u=u or require('uci').cursor()
    local enabled=false
    u:foreach('shadowsocksr','server_global',function(s)if s.enable_server=='1' then enabled=true end end)
    local rows={}
    if enabled then u:foreach('shadowsocksr','server_config',function(s)rows[#rows+1]=s end) end
    return rows
end
function M.config(u)
    local config=model.namespace_config(M.rows(u))
    local used={tcp={},udp={}}
    for _,proto in ipairs({'tcp','udp','tcp6','udp6'}) do
        for line in (fs.readfile('/proc/net/'..proto) or ''):gmatch('[^\n]+') do
            local f={};for v in line:gmatch('%S+') do f[#f+1]=v end
            if f[2] and f[4]==(proto:match('^tcp') and '0A' or '07') then
                local port=f[2]:match(':(%x+)$')
                if port then used[proto:sub(1,3)][tonumber(port,16)]=true end
            end
        end
    end
    for _,inbound in ipairs(config.inbounds) do
        for proto in inbound.settings.network:gmatch('[^,]+') do
            assert(not used[proto][inbound.port],'SS port conflicts with an existing host listener')
        end
    end
    return config
end
function M.loaded()
    return json.parse(fs.readfile('/var/etc/cudy-ss/config.json') or '')
end
function M.matches()
    local ok,config=pcall(M.config)
    return ok and model.same(config,M.loaded())
end
function M.probe()
    local wanted=M.config()
    if #wanted.inbounds==0 or not model.same(wanted,M.loaded()) then return false end
    local tokens=capture('/usr/libexec/cudy-ss-process snapshot')
    for pid in tokens:gmatch('(%d+):%d+') do
        local owned={};local fds=fs.dir('/proc/'..pid..'/fd')
        if fds then for fd in fds do
            local inode=(fs.readlink('/proc/'..pid..'/fd/'..fd) or ''):match('^socket:%[(%d+)%]$')
            if inode then owned[inode]=true end
        end end
        local sockets={tcp={},udp={}}
        for _,proto in ipairs({'tcp','udp','tcp6','udp6'}) do
            for line in (fs.readfile('/proc/'..pid..'/net/'..proto) or ''):gmatch('[^\n]+') do
                local f={};for v in line:gmatch('%S+') do f[#f+1]=v end
                local bind,port=(f[2] or ''):match('^(%x+):(%x+)$')
                if bind and not bind:find('[^0]') and f[4]==(proto:match('^tcp') and '0A' or '07') and owned[f[10]] then
                    sockets[proto:sub(1,3)][tonumber(port,16)]=true
                end
            end
        end
        local all=true
        for _,inbound in ipairs(wanted.inbounds) do
            for proto in inbound.settings.network:gmatch('[^,]+') do if not sockets[proto][inbound.port] then all=false end end
        end
        if all then return true end
    end
    return false
end
function M.ready()
    return fs.access('/var/run/cudy-ss/core-ready') and M.probe()
end
function M.lan()
    local s=json.parse(capture('ubus call network.interface.lan status 2>/dev/null'))
    local lan={addresses={}}
    if type(s)=='table' and s.up then
        lan.device=s.l3_device or s.device
        for _,a in ipairs(s['ipv4-address'] or {}) do if model.ipv4(a.address) then lan.addresses[#lan.addresses+1]=a.address end end
    end
    return lan
end
return M
