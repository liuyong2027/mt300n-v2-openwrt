-- Run with actual ARM64 UCI/nixio/jsonc; redirect all OS paths to /tmp fixtures.
local fs=require('nixio.fs')
local json=require('luci.jsonc')
local base=assert(os.getenv('CUDY_USB_TEST_DIR'))
local source=assert(os.getenv('CUDY_USB_SOURCE'))
assert(base:match('^/tmp/cudy%-usb%-test%-%w+$'))
for _,p in ipairs({'/etc','/etc/config','/etc/samba','/mnt','/root','/var','/var/run'}) do assert(fs.mkdirr(base..p)) end
local function file(path,data) assert(fs.writefile(base..path,data)) end
file('/etc/config/cudy_usb',"config settings 'main'\n option version '1'\n")
file('/etc/config/samba4',"config samba 'main'\n option interface 'lan'\n")
file('/etc/config/fstab','')
file('/etc/samba/smb.conf.template','[global]\n bind interfaces only = yes\n')
assert(fs.symlink('/var/etc/smb.conf',base..'/etc/samba/smb.conf'))
local u=require('uci').cursor(base..'/etc/config',base..'/delta')
assert(fs.mkdir(base..'/delta'))
local function redirect(path)
	if path:match('^/etc/') or path:match('^/root/') or path:match('^/mnt') or path:match('^/var/run/') or path:match('^/usr/libexec/') then return base..path end
	return path
end
local proxy={}
for _,k in ipairs({'readfile','writefile','stat','lstat','mkdir','chmod','unlink','readlink'}) do
	proxy[k]=function(path,...) return fs[k](redirect(path),...) end
end
proxy.rename=function(a,b) return fs.rename(redirect(a),redirect(b)) end
proxy.realpath=function(path)
	local result=fs.realpath(redirect(path))
	if result and result:sub(1,#base)==base then return result:sub(#base+1) end
	return result
end
package.loaded['nixio.fs']=proxy
local runtime=dofile(source..'/luci-app-cudy-usb/root/usr/lib/lua/cudy/usb-runtime.lua')
local engine=dofile(source..'/luci-app-cudy-usb/root/usr/lib/lua/cudy/usb.lua')
package.loaded['cudy.usb']=engine
local e=runtime.new(u)
local disks={{device='/dev/sda1',uuid='ABCD-1234',fstype='vfat'}}
local mounts={}
e.devices=function() local d={};for i,v in ipairs(disks) do local x={};for k,z in pairs(v)do x[k]=z end;d[i]=x end;return d end
e.is_usb=function() return true end
e.mount_at=function(p) return mounts[p] end
e.mount=function(dev,p,kind,ro)
	-- A real mount replaces the 555 internal mountpoint with the disk root.
	-- This fixture provides a writable external-root analogue without mounting.
	assert(fs.chmod(base..p,'700'))
	mounts[p]={device=dev,fstype=kind,rw=ro~='1'};return true
end
e.unmount=function(p) mounts[p]=nil;return true end
e.sync=function() return true end
e.restart=function() return true end
local id=engine.id('ABCD-1234');local target='/mnt/cudy-usb/'..id
engine.enable(u,e,'ABCD-1234','USB','0')
assert(u:get('cudy_usb',id,'uuid')=='abcd-1234')
assert(u:get('samba4',id,'cudy_usb')==id)
assert(fs.stat(base..target..'/.samba-metadata').type=='dir')
engine.guard(u,e,id,target)
assert(json.parse(json.stringify(engine.status(u,e))).volumes[1].ready)
engine.eject(u,e,id,false)
assert(not mounts[target] and not u:get('samba4',id) and e.ejected(id))
engine.reconcile(u,e);assert(not mounts[target])
e.clear_device_ejection('sda1');engine.reconcile(u,e)
assert(mounts[target] and u:get('samba4',id))
-- Metadata removal must repair itself at an authorized reconnect.
assert(fs.rmdir(base..target..'/.samba-metadata'))
engine.reconcile(u,e);assert(fs.stat(base..target..'/.samba-metadata'))
local backup=fs.dir(base..'/root/.cudy-usb-backup')
local found=0
for name in backup do
	if name~='.' and name~='..' then
		found=found+1
		local st=fs.stat(base..'/root/.cudy-usb-backup/'..name)
		assert(st.type=='dir' and st.modestr=='rwx------','private directory mode must be 700')
		assert(fs.stat(base..'/root/.cudy-usb-backup/'..name..'/1.conf').modestr=='rw-------','private config mode must be 600')
	end
end
assert(found>0)
engine.eject(u,e,id,true)
assert(not u:get('cudy_usb',id));e.clear_device_ejection('sda1');engine.reconcile(u,e);assert(not mounts[target])
package.loaded['nixio.fs']=fs
print('PASS real ARM64 UCI/nixio USB consent, lifecycle, metadata recreation and private backup permissions')
