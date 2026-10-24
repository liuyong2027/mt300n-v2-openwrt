-- Node-only deletion: validate the entire selection, then commit once.
local M = {}
local config = 'shadowsocksr'

function M.protected(cursor)
    local used = {}
    local function protect(sid)
        if type(sid) == 'string' and cursor:get(config, sid) == 'servers' then used[sid] = true end
    end
    cursor:foreach(config, 'global', function(row)
        protect(row.global_server); protect(row.udp_relay_server)
    end)
    for _, kind in ipairs({'socks5_proxy', 'http_proxy'}) do
        cursor:foreach(config, kind, function(row) protect(row.server) end)
    end
    return used
end

function M.delete(cursor, selected)
    if type(selected) ~= 'table' or #selected < 1 or #selected > 4096 then return nil, 'invalid_selection' end
    local ids, seen = {}, {}
    local entries = 0
    for key, sid in pairs(selected) do
        entries = entries + 1
        if type(key) ~= 'number' or key < 1 or key % 1 ~= 0 or key > #selected or
            type(sid) ~= 'string' or #sid > 64 or not sid:match('^[A-Za-z0-9_]+$') then
            return nil, 'invalid_selection'
        end
    end
    if entries ~= #selected then return nil, 'invalid_selection' end
    local used = M.protected(cursor)
    for _, sid in ipairs(selected) do
        if cursor:get(config, sid) ~= 'servers' then return nil, 'stale_selection' end
        if used[sid] then return nil, 'node_in_use' end
        if not seen[sid] then ids[#ids + 1] = sid; seen[sid] = true end
    end
    local changes = cursor:changes(config)
    if type(changes) == 'table' and next(changes) then return nil, 'pending_changes' end
    for _, sid in ipairs(ids) do
        if not cursor:delete(config, sid) then
            cursor:unload(config)
            return nil, 'delete_failed'
        end
    end
    if not cursor:commit(config) then
        cursor:unload(config)
        return nil, 'commit_failed'
    end
    return #ids
end

return M
