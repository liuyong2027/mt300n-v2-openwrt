local fs=require('nixio.fs')
local root=assert(arg[1]);assert(root:match('^/tmp/cudy%-webfiles%-storage%-test%.[%w]+$'))
local module=dofile(assert(arg[2]))
local passed=0
local function quote(value) return "'"..value:gsub("'","'\\''").."'" end
local function command(value) assert(os.execute(value)==0,value) end
local function directory(path,mode) command('mkdir -p '..quote(path));assert(fs.chmod(path,mode or '755')) end
local marker='Cudy WebFiles LuCI private settings v0.2\n'
local fixture={marker=marker,['account.key']=string.rep('k',32),['accounts.enc']='synthetic-encrypted-account-fixture',['tls.enc']='synthetic-encrypted-certificate-fixture',['public-tls.enc']='synthetic-public-IP-TLS',['public-domain-tls.enc']='synthetic-DDNS-TLS',['last-stop.json']='synthetic-stop-record'}
local function files(path)
    directory(path)
    for name,bytes in pairs(fixture) do assert(fs.writefile(path..'/'..name,bytes));assert(fs.chmod(path..'/'..name,'600')) end
end
local function unchanged(path)
    for name,bytes in pairs(fixture) do assert(fs.readfile(path..'/'..name)==bytes,name);assert(fs.lstat(path..'/'..name).modestr=='rw-------') end
end
local function pass(name) passed=passed+1;print('PASS '..name) end
local function reject(path)
    local before=fs.lstat(path).modestr
    local ok=module.prepare(path,0);assert(not ok);assert(fs.lstat(path).modestr==before)
end
assert(module.prepare(root..'/absent',0));assert(not fs.lstat(root..'/absent'));pass('missing directory remains absent')
local path=root..'/valid';files(path);local ok,changed=module.prepare(path,0);assert(ok and changed);assert(fs.lstat(path).modestr=='rwx------');unchanged(path);pass('root755 restored to700 without changing files')
ok,changed=module.prepare(path,0);assert(ok and not changed);unchanged(path);pass('already700 is idempotent')
path=root..'/writable';files(path);assert(fs.chmod(path,'777'));reject(path);pass('writable directory rejected')
path=root..'/wrong-marker';files(path);assert(fs.writefile(path..'/marker','other-owner-marker'));reject(path);pass('foreign marker rejected')
path=root..'/public-file';files(path);assert(fs.chmod(path..'/account.key','644'));reject(path);pass('public private-file mode rejected')
path=root..'/directory-link';files(root..'/directory-target');command('ln -s '..quote(root..'/directory-target')..' '..quote(path));reject(path);assert(fs.lstat(root..'/directory-target').modestr=='rwxr-xr-x');pass('directory symlink rejected')
path=root..'/file-link';files(path);assert(fs.unlink(path..'/account.key'));command('ln -s '..quote(root..'/valid/account.key')..' '..quote(path..'/account.key'));reject(path);unchanged(root..'/valid');pass('private-file symlink rejected')
path=root..'/wrong-owner';files(path);command('chown 1001:1001 '..quote(path..'/account.key'));reject(path);pass('foreign private-file owner rejected')
path=root..'/hard-link';files(path);command('ln '..quote(path..'/account.key')..' '..quote(root..'/key-link-fixture'));reject(path);pass('multiply linked private file rejected')
local source=root..'/archive-source';files(source..'/etc/cudy-webfiles');assert(fs.chmod(source..'/etc/cudy-webfiles','700'))
command('tar -czf '..quote(root..'/selected-files.tar.gz')..' -C '..quote(source)..' etc/cudy-webfiles/marker etc/cudy-webfiles/account.key etc/cudy-webfiles/accounts.enc etc/cudy-webfiles/tls.enc etc/cudy-webfiles/public-tls.enc etc/cudy-webfiles/public-domain-tls.enc etc/cudy-webfiles/last-stop.json')
local restored=root..'/archive-restored';directory(restored,'700');command('umask 022; tar -xzf '..quote(root..'/selected-files.tar.gz')..' -C '..quote(restored))
path=restored..'/etc/cudy-webfiles';assert(fs.lstat(path).modestr=='rwxr-xr-x','Tar no-parent fixture did not reproduce755')
ok,changed=module.prepare(path,0);assert(ok and changed);assert(fs.lstat(path).modestr=='rwx------');unchanged(path);pass('actual tar file-list restore reproduced and corrected')
assert(passed==11);print('PASS all11 native storage restoration regressions')
