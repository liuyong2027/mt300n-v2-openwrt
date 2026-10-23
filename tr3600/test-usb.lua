-- Pure failure/lifecycle fixtures; no router files or real devices are touched.
local M=dofile(arg[1] or 'tr3600/luci-app-cudy-usb/root/usr/lib/lua/cudy/usb.lua')
local checks=0
local function copy(x) if type(x)~='table' then return x end;local v={};for k,z in pairs(x) do v[k]=copy(z) end;return v end
local function fixture()
	local d={cudy_usb={main={['.type']='settings'}},fstab={},samba4={main={['.type']='samba',interface='lan'},other={['.type']='sambashare',name='Documents',path='/other'}}}
	local u={}
	function u:get_all(c,s) return copy(d[c][s]) end
	function u:get(c,s,o) local x=d[c][s]; return x and (o and x[o] or x['.type']) end
	function u:set(c,s,o,v) d[c][s]=d[c][s] or {}; if v==nil then d[c][s]['.type']=o else d[c][s][o]=v end;return true end
	function u:delete(c,s,o) if o then d[c][s][o]=nil else d[c][s]=nil end;return true end
	function u:foreach(c,t,f) local snapshot=copy(d[c]);for n,x in pairs(snapshot) do if x['.type']==t then x['.name']=n;f(x) end end end
	function u:commit(c) if u.fail_commit==c then u.fail_commit=nil;return false end;return true end
	local e={disks={{device='/dev/sda1',uuid='ABCD-1234',fstype='vfat'}},mounts={},dirs={},links={},flags={},commands={},legacy=true}
	function e.devices() return copy(e.disks) end
	function e.is_usb(dev) return not e.not_usb end
	function e.realpath(path) return e.links[path] or path end
	function e.is_link(path) return e.links[path]~=nil end
	function e.mount_at(path) return copy(e.mounts[path]) end
	function e.mkdir(path) if e.bad_mkdir then return false end;e.dirs[path]=true;return true end
	function e.mkdir_target(path) return not e.is_link(path) and e.mkdir(path) end
	function e.metadata_exists(path) return e.dirs[path..'/.samba-metadata'] and not e.is_link(path..'/.samba-metadata') end
	function e.mount(dev,path,kind,ro,original)
		if e.mount_fail then return false end;e.commands[#e.commands+1]={'mount',dev,path,kind,ro};e.mounts[path]={device=dev,fstype=kind,rw=ro~='1'};return true
	end
	function e.unmount(path) if e.busy then return false end;e.mounts[path]=nil;e.commands[#e.commands+1]={'umount',path};return true end
	function e.sync() return not e.sync_fail end
	function e.restart() if e.restart_fail then e.restart_fail=nil;return false end;return true end
	function e.snapshot() return copy(d) end
	function e.restore(snap) for c,x in pairs(snap) do d[c]=copy(x) end end
	function e.ejected(id) return e.flags[id] end
	function e.mark_ejected(id,x) e.flags[id]=x end
	function e.legacy_guard(uuid) return e.legacy end
	function e.clean_legacy_template() e.cleaned=true;return true end
	function e.lan_only() return not e.wan_enabled end
	return u,e,d
end
local function test(name,f) local ok,err=pcall(f);assert(ok,name..': '..tostring(err));checks=checks+1;print('PASS '..name) end
local function rejects(f) local ok=pcall(f);assert(not ok,'unexpected success') end
local uuid='abcd-1234';local id=M.id(uuid);local target='/mnt/cudy-usb/'..id
test('unknown disks remain unshared',function() local u,e,d=fixture();M.reconcile(u,e);assert(#e.commands==0 and not d.samba4[id]);assert(#M.status(u,e).devices==1) end)
test('explicit consent mounts, shares, and creates metadata',function() local u,e,d=fixture();M.enable(u,e,uuid,'USB','0');assert(d.cudy_usb[id].uuid==uuid and d.samba4[id].guest_only=='yes');assert(e.dirs[target..'/.samba-metadata']);M.guard(u,e,id,target);assert(d.samba4.other.path=='/other') end)
test('different disk never inherits previous share',function() local u,e,d=fixture();M.enable(u,e,uuid,'USB','0');e.mounts={};e.disks[1].uuid='5678-1234';M.reconcile(u,e);assert(not d.samba4[id] and #e.commands==1);rejects(function()M.guard(u,e,id,target)end) end)
test('same UUID survives device renumber and repairs missing metadata',function() local u,e,d=fixture();M.enable(u,e,uuid,'USB','0');e.mounts={};e.dirs={};e.disks[1].device='/dev/sdb2';M.reconcile(u,e);assert(e.mounts[target].device=='/dev/sdb2' and e.dirs[target..'/.samba-metadata']) end)
test('duplicate UUID is rejected',function() local u,e,d=fixture();local a=copy(e.disks[1]);a.device='/dev/sdb1';e.disks[2]=a;rejects(function()M.enable(u,e,uuid,'USB','0')end);assert(not d.cudy_usb[id] and #e.commands==0) end)
test('non USB and unsupported encrypted disks ignored',function() local u,e=fixture();e.not_usb=true;assert(#M.devices(e)==0);e.not_usb=false;e.disks[1].fstype='crypto_LUKS';assert(#M.devices(e)==0) end)
test('shell/config injection, reserved and duplicate names rejected',function() local u,e,d=fixture();for _,x in ipairs({'global','../root','x;reboot','a\nforce user=root'}) do rejects(function()M.enable(u,e,uuid,x,'0')end) end;rejects(function()M.enable(u,e,'a;reboot','USB','0')end);rejects(function()M.enable(u,e,uuid,'documents','0')end);assert(#e.commands==0) end)
test('mounted elsewhere and occupied/symlink targets rejected',function() local u,e=fixture();e.disks[1].mount='/overlay';rejects(function()M.enable(u,e,uuid,'USB','0')end);e.disks[1].mount=nil;e.links[target]='/root';rejects(function()M.enable(u,e,uuid,'USB','0')end);assert(#e.commands==0) end)
test('mount failure leaves no authorization',function() local u,e,d=fixture();e.mount_fail=true;rejects(function()M.enable(u,e,uuid,'USB','0')end);assert(not d.cudy_usb[id] and not d.samba4[id]) end)
test('config and daemon failures roll back',function() for _,kind in ipairs({'commit','restart','metadata'}) do local u,e,d=fixture();if kind=='commit' then u.fail_commit='samba4' elseif kind=='restart' then e.restart_fail=true else e.links[target..'/.samba-metadata']='/root' end;rejects(function()M.enable(u,e,uuid,'USB','0')end);assert(not d.cudy_usb[id] and not d.samba4[id] and not e.mount_at(target)) end end)
test('read-only mount requires no writable metadata',function() local u,e,d=fixture();M.enable(u,e,uuid,'USB','1');assert(not e.mounts[target].rw and d.samba4[id].read_only=='yes' and not e.dirs[target..'/.samba-metadata']);M.guard(u,e,id,target) end)
test('guard rejects wrong share path and unmounted internal directory',function() local u,e=fixture();M.enable(u,e,uuid,'USB','0');rejects(function()M.guard(u,e,id,'/root')end);e.mounts={};rejects(function()M.guard(u,e,id,target)end) end)
test('metadata symlink/database symlink fail closed',function() local u,e,d=fixture();M.enable(u,e,uuid,'USB','0');e.links[target..'/.samba-metadata/xattr.tdb']='/etc/shadow';M.reconcile(u,e);assert(not d.samba4[id]);rejects(function()M.guard(u,e,id,target)end) end)
test('status does not repair or fail on absent disk',function() local u,e=fixture();M.enable(u,e,uuid,'USB','0');e.dirs={};assert(not M.status(u,e).volumes[1].ready and not next(e.dirs));e.mounts={};e.disks={};assert(not M.status(u,e).volumes[1].ready) end)
test('safe eject suspends remount until plug event and preserves consent',function() local u,e,d=fixture();M.enable(u,e,uuid,'USB','0');M.eject(u,e,id,false);assert(d.cudy_usb[id] and not d.samba4[id] and not e.mount_at(target));M.reconcile(u,e);assert(not e.mount_at(target));e.mark_ejected(id,false);M.reconcile(u,e);assert(d.samba4[id] and e.mount_at(target)) end)
test('busy eject reports failure and restores share',function() local u,e,d=fixture();M.enable(u,e,uuid,'USB','0');e.busy=true;rejects(function()M.eject(u,e,id,false)end);assert(d.samba4[id] and e.mount_at(target) and not e.ejected(id));e.sync_fail=true;rejects(function()M.eject(u,e,id,false)end) end)
test('forget removes consent and does not remount',function() local u,e,d=fixture();M.enable(u,e,uuid,'USB','0');M.eject(u,e,id,true);e.mark_ejected(id,false);M.reconcile(u,e);assert(not d.cudy_usb[id] and not e.mount_at(target)) end)
test('non LAN Samba prevents enable and withdraws managed shares',function() local u,e,d=fixture();e.wan_enabled=true;rejects(function()M.enable(u,e,uuid,'USB','0')end);e.wan_enabled=false;M.enable(u,e,uuid,'USB','0');e.wan_enabled=true;M.reconcile(u,e);assert(not d.samba4[id] and d.samba4.other) end)
test('old project disk adopted once including unplugged disks',function() local u,e,d=fixture();d.fstab.tr3600_usb={['.type']='mount',uuid='ABCD-1234',target='/mnt/usb',fstype='vfat',enabled='1'};d.samba4.usb={['.type']='sambashare',path='/mnt/usb',name='USB',guest_ok='yes',guest_only='yes',read_only='no'};e.disks={};M.migrate(u,e);assert(e.cleaned and not d.fstab.tr3600_usb and not d.samba4.usb and d.cudy_usb[id].target=='/mnt/usb');M.migrate(u,e);e.disks={{device='/dev/sdc1',uuid='ABCD-1234',fstype='vfat'}};M.reconcile(u,e);assert(d.samba4[id].name=='USB' and e.dirs['/mnt/usb/.samba-metadata']) end)
test('unrecognized legacy owner configuration untouched',function() local u,e,d=fixture();d.fstab.tr3600_usb={uuid='ABCD-1234',target='/overlay'};M.migrate(u,e);assert(d.fstab.tr3600_usb.target=='/overlay' and not e.cleaned) end)
print('PASS USB lifecycle '..checks..' tests')
