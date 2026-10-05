-- Real ARM64 nixio/jsonc with disposable files; no real LED or Wi-Fi writes.
local fs=require('nixio.fs')
local json=require('luci.jsonc')
local base=assert(os.getenv('CUDY_PERMISSION_TEST_DIR'))
local root=assert(os.getenv('CUDY_TEST_ROOT'))
local source=assert(os.getenv('CUDY_PERMISSION_SOURCE'))
assert(base:match('^/tmp/cudy%-permissions%-%w+$'))
assert(fs.mkdir(base) or fs.access(base))
assert(fs.chmod(base,'700'))
if os.getenv('CUDY_PERMISSION_CASE')~='wifi' then
    local runtime=dofile(source..'/luci-app-cudy-led/root/usr/lib/lua/cudy/led-runtime.lua')
    runtime.dir=base..'/led'
    assert(runtime.atomic(runtime.dir..'/sample.json',{result=true}))
    assert(runtime.read(runtime.dir..'/sample.json').result==true)
    print('PASS real nixio LED atomic JSON persistence')
    if os.getenv('CUDY_PERMISSION_CASE')=='led' then return end
end

-- Redirect the production wrapper's private backup and board read only.
-- Other filesystem operations, including chmod, use the actual nixio module.
local backup='/etc/cudy-wifi-backup.json'
local function redirected(path)
    if path:sub(1,#backup)==backup then return base..'/wifi.json'..path:sub(#backup+1) end
    return path
end
local proxy={}
for _,name in ipairs({'access','writefile','remove'}) do
    proxy[name]=function(path,...) return fs[name](redirected(path),...) end
end
proxy.chmod=function(path,mode) return fs.chmod(redirected(path),mode) end
proxy.rename=function(a,b) return fs.rename(redirected(a),redirected(b)) end
proxy.readfile=function(path)
    if path=='/tmp/sysinfo/board_name' then return 'cudy,tr3600-v1\n' end
    return fs.readfile(redirected(path))
end
package.loaded['nixio.fs']=proxy
package.loaded['cudy.wifi']={apply=function(_,env)
    assert(env.board()=='cudy,tr3600-v1')
    assert(env.save({test='no credentials'}))
    assert(env.load().test=='no credentials')
    return true,'PASS real nixio Wi-Fi production backup save/load'
end}
local old_arg,old_exit=arg,os.exit
arg={'boot'}
local exit_code
os.exit=function(code) exit_code=code end
local ok,err=pcall(dofile,source..'/luci-app-cudy-wifi/root/usr/libexec/cudy-wifi-config')
arg,os.exit=old_arg,old_exit
package.loaded['nixio.fs']=fs
assert(ok,err); assert(exit_code==0)
assert(json.parse(fs.readfile(base..'/wifi.json')).test=='no credentials')

