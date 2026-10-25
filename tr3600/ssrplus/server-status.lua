-- A watcher or client process does not prove that a server is listening.
-- Ordinary SS readiness checks the requested configuration, owned core and
-- all selected TCP/UDP listeners inside its network namespace.
local cudy_ss_requested = false
local cudy_other_ports = {}
if uci:get_first('shadowsocksr', 'server_global', 'enable_server', '0') == '1' then
    uci:foreach('shadowsocksr', 'server_config', function(row)
        if row.enable == '1' then
            if row.type == 'shadowsocks' then
                cudy_ss_requested = true
            else
                local port = tonumber(row.server_port)
                if port and port >= 1 and port <= 65535 and port % 1 == 0 then
                    cudy_other_ports[port] = true
                end
            end
        end
    end)
end
if cudy_ss_requested and luci.sys.call('/usr/libexec/cudy-ssr-servers ready >/dev/null 2>&1') == 0 then
    server_run = 1
end

-- Other server types retain their host runtime. Inspect exact argv[0] paths
-- created by ln_start_bin and sockets owned by that same process, rather than
-- matching unrelated words anywhere in a combined ps listing.
local function cudy_host_server_listening(pid)
    local base = '/proc/' .. pid
    local command = (nixio.fs.readfile(base .. '/cmdline') or ''):match('^[^%z]+') or ''
    local name = command:match('^/var/etc/ssrplus/bin/([^/]+)$')
    if not name or not (name == 'ss-server' or name == 'ssr-server' or
        name:match('^ss%-server%-%d+$') or name:match('^ssr%-server%-%d+$') or
        name:match('^xray%-server%-%d+$') or name:match('^mihomo%-server%-%d+$')) then
        return false
    end
    local owned = {}
    local fds = nixio.fs.dir(base .. '/fd')
    if fds then
        for fd in fds do
            local inode = (nixio.fs.readlink(base .. '/fd/' .. fd) or ''):match('^socket:%[(%d+)%]$')
            if inode then owned[inode] = true end
        end
    end
    for _, protocol in ipairs({'tcp', 'udp', 'tcp6', 'udp6'}) do
        for line in (nixio.fs.readfile(base .. '/net/' .. protocol) or ''):gmatch('[^\n]+') do
            local fields = {}
            for field in line:gmatch('%S+') do fields[#fields + 1] = field end
            local port = (fields[2] or ''):match(':(%x+)$')
            if port and cudy_other_ports[tonumber(port, 16)] and owned[fields[10]] and
                fields[4] == (protocol:match('^tcp') and '0A' or '07') then
                return true
            end
        end
    end
    return false
end
if server_run == 0 and next(cudy_other_ports) then
    local processes = nixio.fs.dir('/proc')
    if processes then
        for pid in processes do
            if pid:match('^%d+$') and cudy_host_server_listening(pid) then
                server_run = 1
                break
            end
        end
    end
end
