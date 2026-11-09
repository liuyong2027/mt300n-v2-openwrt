function M.identity()
    local ike=hash('uci -q get mango_ikev2.main.enabled; uci -q get mango_ikev2.main.mode; ip -4 addr show xfrm-mango 2>/dev/null')
    local config=hash('uci -q export shadowsocksr')
    local data=M.uplink_data():gsub("'", "'\\''")
    local uplink=hash("printf '%s' '"..data.."'")
    local generation=hash('pidof xray v2ray ss-redir ssr-redir hysteria mihomo charon 2>/dev/null')
    if config and uplink then return (ike or 'ike')..':'..config..':'..uplink..':'..(generation or 'stopped') end
end
local function lock_held(path)
    -- IKEv2 and SSR leave flock files behind; only a live holder is "busy".
    if not fs.access(path) then return false end
    local r = os.execute("flock -n '" .. path .. "' true >/dev/null 2>&1")
    if r == true or r == 0 then return false end
    return true
end
function M.snapshot()
    local u=uci.cursor()
    local ike_on=u:get('mango_ikev2','main','enabled')=='1'
    local ike_mode=u:get('mango_ikev2','main','mode') or 'gfw'
    local global
    u:foreach('shadowsocksr','global',function(s) if not global then global=s end end)
    global=global or {}
    local active=global.global_server or 'nil'
    local runmode=global.run_mode or 'router'
    local mode,ready
    if ike_on and ike_mode ~= 'direct' then
        -- IKEv2 owns egress; do not require SSR ss_spec/xray.
        mode=({split='split',gfw='gfw',global='global'})[ike_mode] or 'split'
        ready=os.execute('ip link show xfrm-mango >/dev/null 2>&1')==0
            and os.execute('ip -4 route show table 101 | grep -q .')==0
    else
        mode=(active=='nil' or active=='') and 'direct' or ({router='split',all='global',gfw='gfw'})[runmode] or 'global'
        ready=mode=='direct' or os.execute('nft list table inet ss_spec >/dev/null 2>&1')==0
    end
    local routes=M.capture('ip -4 route show table main default')
    local uplink=routes=='' and 1 or 0
    return {board=M.board(),now=M.now(),id=M.identity(),mode=mode,
        failover=false,busy=lock_held('/var/lock/ssrplus.lock') or lock_held('/var/lock/mango-ikev2-resource.lock'),uplink=uplink,
        ready=ready,
        suspended=M.blocked(),clock_ok=fs.access(M.dir..'/clock-synced') and os.time()>1704067200,
        minute=tonumber(os.date('%H'))*60+tonumber(os.date('%M'))}
end
function M.source(s) return 'led' end
