-- Restore only the directory mode lost when sysupgrade archives list files.
-- Account keys, encrypted accounts and certificates are never read or replaced.
local fs = require('nixio.fs')
local M = {}
local marker = 'Cudy WebFiles LuCI private settings v0.2\n'
function M.prepare(path, owner)
    local directory = fs.lstat(path)
    if not directory then return true, false end
    if directory.type ~= 'dir' or directory.uid ~= owner then
        return nil, 'Private directory identity mismatch'
    end
    if directory.modestr == 'rwx------' then return true, false end
    if directory.modestr ~= 'rwxr-xr-x' then
        return nil, 'Unexpected private directory permissions'
    end
    local stamp = fs.lstat(path .. '/marker')
    if not stamp or stamp.type ~= 'reg' or stamp.uid ~= owner or
        stamp.modestr ~= 'rw-------' or stamp.nlink ~= 1 or stamp.size > 256 then
        return nil, 'Private marker identity mismatch'
    end
    if fs.readfile(path .. '/marker') ~= marker then
        return nil, 'Private directory marker mismatch'
    end
    for name in fs.dir(path) do
        local item = fs.lstat(path .. '/' .. name)
        if not item or item.type ~= 'reg' or item.uid ~= owner or
            item.modestr ~= 'rw-------' or item.nlink ~= 1 then
            return nil, 'Private file identity or permissions mismatch'
        end
    end
    -- String modes are required by the deployed nixio.fs API.
    if not fs.chmod(path, '700') then return nil, 'Private directory chmod failed' end
    local final = fs.lstat(path)
    if not final or final.type ~= 'dir' or final.uid ~= owner or final.modestr ~= 'rwx------' then
        return nil, 'Private directory verification failed'
    end
    return true, true
end
return M
