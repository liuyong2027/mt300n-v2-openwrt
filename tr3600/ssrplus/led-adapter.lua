function M.identity()
    local config=hash('uci -q export shadowsocksr')
    local data=M.uplink_data():gsub("'", "'\\''")
    local uplink=hash("printf '%s' '"..data.."'")
    local generation=hash('pidof xray v2ray ss-redir ssr-redir hysteria mihomo 2>/dev/null')
    if config and uplink then return config..':'..uplink..':'..(generation or 'stopped') end
end
function M.snapshot()
    local u=uci.cursor()
    local global
    u:foreach('shadowsocksr','global',function(s) if not global then global=s end end)
    global=global or {}
    local active=global.global_server or 'nil'
    local runmode=global.run_mode or 'router'
    local mode=(active=='nil' or active=='') and 'direct' or ({router='split',all='global',gfw='gfw'})[runmode] or 'global'
    local routes=M.capture('ip -4 route show table main default')
    local uplink=routes=='' and 1 or 0
    return {board=M.board(),now=M.now(),id=M.identity(),mode=mode,
        failover=false,busy=fs.access('/var/lock/ssrplus.lock'),uplink=uplink,
        ready=mode=='direct' or os.execute('nft list table inet ss_spec >/dev/null 2>&1')==0,
        suspended=M.blocked(),clock_ok=fs.access(M.dir..'/clock-synced') and os.time()>1704067200,
        minute=tonumber(os.date('%H'))*60+tonumber(os.date('%M'))}
end
function M.source(s) return 'led' end

