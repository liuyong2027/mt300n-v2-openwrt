function act_delete_nodes()
    local function reply(code, result)
        luci.http.status(code)
        luci.http.prepare_content('application/json')
        luci.http.write_json(result)
    end
    if luci.http.getenv('REQUEST_METHOD') ~= 'POST' then
        reply(405, {ret=0, error='post_required'}); return
    end
    local raw = luci.http.formvalue('ids') or ''
    if type(raw) ~= 'string' or #raw > 131072 then reply(400, {ret=0, error='invalid_selection'}); return end
    local parsed, ids = pcall(json.parse, raw)
    if not parsed then reply(400, {ret=0, error='invalid_selection'}); return end
    local helper = dofile('/usr/share/shadowsocksr/bulk_delete.lua')
    -- Keep this session's staged edits intact. LuCI's RPC commit emits a
    -- config.change event and reloads SSR even when only unused nodes change.
    local pending = require('luci.model.uci').cursor():changes('shadowsocksr')
    if type(pending) ~= 'table' then reply(500, {ret=0, error='delete_failed'}); return end
    if next(pending) then reply(409, {ret=0, error='pending_changes'}); return end
    -- Native UCI commits once without publishing a service reload event.
    -- The helper also rejects native pending edits and all service references.
    local cursor = require('uci').cursor()
    local ok, count, reason = pcall(helper.delete, cursor, ids)
    if not ok then reply(500, {ret=0, error='delete_failed'}); return end
    if not count then
        local conflict = reason == 'node_in_use' or reason == 'pending_changes' or reason == 'stale_selection'
        local failure = reason == 'delete_failed' or reason == 'commit_failed'
        reply(conflict and 409 or (failure and 500 or 400), {ret=0, error=reason}); return
    end
    nixio.fs.remove(SERVER_DETECT_CACHE)
    reply(200, {ret=1, deleted=count})
end
