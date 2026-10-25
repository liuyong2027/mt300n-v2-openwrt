-- Move the private SS credentials once; the server_config row is authoritative.
local M={section='cudy_zt_private',marker='/etc/cudy-ssrplus/ss-server-v2.done'}
function M.run(u,fs)
    u=u or require('uci').cursor()
    fs=fs or require('nixio.fs')
    if fs.access(M.marker) then return false end
    local directory='/etc/cudy-ssrplus'
    if not fs.access(directory) then assert(fs.mkdir(directory)) end
    assert(fs.chmod(directory,'700'))
    local backup=directory..'/cudy_ss.before-server-v2'
    local original=fs.readfile('/etc/config/cudy_ss')
    if original and not fs.access(backup) then
        assert(fs.writefile(backup,original));assert(fs.chmod(backup,'600'))
    end
    local existing=u:get_all('shadowsocksr',M.section)
    u:foreach('shadowsocksr','server_config',function(row)
        assert(row.cudy_private~='1' or row['.name']==M.section,'Another private SS row already exists')
    end)
    if existing then
        assert(existing['.type']=='server_config' and existing.cudy_private=='1' and
            existing.cudy_access=='zerotier','Private SS section name is already owned')
        -- Includes retries after commit: never replace edits with legacy values.
    else
        local old=u:get_all('cudy_ss','main') or {}
        assert(u:set('shadowsocksr',M.section,'server_config'))
        local fields={type='shadowsocks',enable=old.enabled or '0',
            server_port=old.port or '8388',ss_method=old.method or 'aes-128-gcm',
            ss_password=old.password,ss_network='tcp,udp',remarks='ZeroTier private SS',
            cudy_private='1',cudy_access='zerotier',
            cudy_zt_network_id=old.network_id,cudy_zt_interface=old.interface,
            cudy_zt_listen=old.listen,cudy_zt_subnet=old.subnet}
        for key,value in pairs(fields) do assert(u:set('shadowsocksr',M.section,key,value)) end
        assert(u:commit('shadowsocksr'))
    end
    -- The global server switch is deliberately not enabled by migration.
    assert(fs.writefile(M.marker,'1\n'));assert(fs.chmod(M.marker,'600'))
    return true
end
return M
