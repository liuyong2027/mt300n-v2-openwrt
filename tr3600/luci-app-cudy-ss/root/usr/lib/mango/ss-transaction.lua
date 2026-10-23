-- Pure coordinator: environment callbacks own locking, private snapshots,
-- staged preflight, firewall transactions and production service verification.
-- Never expose callback error text: it may contain candidate credentials.
local M = {}

local required = {
    'snapshot', 'stage', 'protect', 'commit', 'guard', 'reload', 'verify',
    'finalize', 'restore', 'rollback_guard', 'rollback_verify'
}

local function attempt(env, name, ...)
    local ok, result = pcall(env[name], ...)
    return ok and result == true
end

local function rollback(env, old)
    -- Always attempt every recovery stage. An exception or false return cannot
    -- skip guard repair, restart or verification of the previous state.
    local restored = attempt(env, 'restore', old)
    local guarded = attempt(env, 'rollback_guard', old)
    local reloaded = attempt(env, 'reload')
    local verified = attempt(env, 'rollback_verify', old)
    local ok = restored and guarded and reloaded and verified
    -- Retired protection remains until the old state has been verified.
    if ok then ok = attempt(env, 'finalize', old) end
    return ok
end

function M.apply(candidate, env)
    if type(env) ~= 'table' then return false, 'invalid environment', nil end
    for _, name in ipairs(required) do
        if type(env[name]) ~= 'function' then
            return false, 'invalid environment', nil
        end
    end

    local captured, old = pcall(env.snapshot)
    if not captured or old == nil or old == false then
        return false, 'snapshot failed', nil
    end
    if not attempt(env, 'stage', candidate) then
        return false, 'stage failed', nil
    end

    -- protect() may partially mutate before returning false or throwing. From
    -- this point every failure must recover the old config, guard and service.
    if not attempt(env, 'protect', old, candidate) then
        return false, 'protection failed', rollback(env, old)
    end
    for _, step in ipairs({'commit', 'guard', 'reload', 'verify', 'finalize'}) do
        local ok
        if step == 'reload' then ok = attempt(env, step)
        else ok = attempt(env, step, candidate) end
        if not ok then
            return false, step .. ' failed', rollback(env, old)
        end
    end
    return true, 'applied', nil
end

return M
