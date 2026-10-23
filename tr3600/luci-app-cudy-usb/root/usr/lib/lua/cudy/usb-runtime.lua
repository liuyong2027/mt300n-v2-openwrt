local fs=require('nixio.fs')
local M={}
local function quote(s) return "'"..s:gsub("'","'\\''").."'" end
local function run(command) return os.execute(command)==0 end
local function read(path) return fs.readfile(path) end
local function exists(path) return fs.lstat(path)~=nil end
local function atomic(path,data)
	local tmp=path..'.cudy-tmp'
	if fs.lstat(tmp) then return false end
	if not fs.writefile(tmp,data) then return false end
	if not fs.chmod(tmp,'600') then fs.unlink(tmp); return false end
	if not fs.rename(tmp,path) then fs.unlink(tmp); return false end
	return true
end
function M.new(u)
	local e={}
	local state='/var/run/cudy-usb'
	function e.is_link(path) local st=fs.lstat(path); return st and st.type=='lnk' or false end
	function e.realpath(path) return fs.realpath(path) end
	function e.is_usb(device)
		local path=fs.realpath('/sys/class/block/'..device:sub(6))
		return path and path:match('/usb%d+/')~=nil
	end
	function e.devices()
		local p=assert(io.popen('/sbin/block info 2>/dev/null'))
		local data=p:read(131072) or ''; p:close(); local rows={}
		for line in data:gmatch('[^\n]+') do
			local dev=line:match('^(/dev/sd%l+%d*): ')
			if dev then
				local function field(k) return line:match('%f[%w]'..k..'="([^"]*)"') end
				rows[#rows+1]={device=dev,uuid=field('UUID'),label=field('LABEL') or '',fstype=field('TYPE'),mount=field('MOUNT')}
			end
		end
		return rows
	end
	function e.mount_at(target)
		for line in (read('/proc/mounts') or ''):gmatch('[^\n]+') do
			local dev,path,kind,options=line:match('^(%S+) (%S+) (%S+) (%S+)')
			if path==target then return {device=dev,fstype=kind,rw=(','..options..','):match(',rw,')~=nil} end
		end
	end
	function e.mkdir(path)
		if e.is_link(path) then return false end
		local st=fs.stat(path)
		if st then return st.type=='dir' end
		return fs.mkdir(path) and true or false
	end
	function e.mkdir_target(target)
		local parent=target=='/mnt/usb' and '/mnt' or '/mnt/cudy-usb'
		if e.realpath('/mnt')~='/mnt' or e.is_link('/mnt') then return false end
		if not e.mkdir(parent) or e.realpath(parent)~=parent then return false end
		if not e.mkdir(target) or e.realpath(target)~=target then return false end
		-- This mode applies only to an unmounted empty mount point, never disk data.
		if not e.mount_at(target) and not fs.chmod(target,'555') then return false end
		return true
	end
	function e.metadata_exists(target)
		local path=target..'/.samba-metadata'; local st=fs.lstat(path)
		return st and st.type=='dir' and fs.realpath(path)==path and not e.is_link(path..'/xattr.tdb')
	end
	function e.mount(device,target,kind,readonly,original)
		local options=(readonly=='1' and 'ro' or 'rw')..',noatime,nosuid,nodev,noexec'
		if original=='vfat' or original=='exfat' or kind=='ntfs3' then
			options=options..',uid=65534,gid=65534,fmask=0111,dmask=0000'
		end
		if original=='vfat' then options=options..',utf8' end
		return run('/usr/libexec/timeout-coreutils 15 /bin/mount -t '..quote(kind)..' -o '..quote(options)..' '..quote(device)..' '..quote(target)..' >/dev/null 2>&1')
	end
	function e.unmount(target)
		return run('/usr/libexec/timeout-coreutils 10 /bin/umount '..quote(target)..' >/dev/null 2>&1')
	end
	function e.sync() return run('/usr/libexec/timeout-coreutils 15 /bin/sync') end
	function e.restart()
		return run('/usr/libexec/timeout-coreutils 15 /etc/init.d/samba4 restart >/dev/null 2>&1')
	end
	function e.lan_only()
		local safe=true; local found=false
		u:foreach('samba4','samba',function(s)
			found=true; if s.interface and s.interface~='lan' then safe=false end
		end)
		local st=fs.lstat('/etc/samba/smb.conf')
		if st and st.type~='lnk' then safe=false end
		if st and st.type=='lnk' and fs.readlink('/etc/samba/smb.conf')~='/var/etc/smb.conf' then safe=false end
		local template=read('/etc/samba/smb.conf.template') or ''
		local binding,section
		for line in (template..'\n'):gmatch('(.-)\n') do
			local header=line:match('^%s*%[([^%]]+)%]')
			if header then section=header:lower(); if section~='global' then safe=false end end
			local value=line:lower():match('^%s*bind interfaces only%s*=%s*(.-)%s*$')
			if value and section=='global' then binding=value end
		end
		return safe and found and binding=='yes'
	end
	function e.ejected(id) return exists(state..'/'..id) end
	function e.mark_ejected(id,value)
		assert(id:match('^usb_[%w_]+$'))
		assert(e.mkdir(state),'不能创建状态目录')
		if value then assert(fs.writefile(state..'/'..id,'ejected\n')) else fs.unlink(state..'/'..id) end
	end
	function e.clear_device_ejection(device)
		if not device or not device:match('^sd%l+%d*$') then return end
		for _,d in ipairs(e.devices()) do
			if d.device=='/dev/'..device and d.uuid then
				local engine=require('cudy.usb')
				if engine.uuid(d.uuid) then e.mark_ejected(engine.id(d.uuid),false) end
			end
		end
	end
	local config_paths={'/etc/config/cudy_usb','/etc/config/samba4','/etc/config/fstab','/etc/samba/smb.conf.template','/etc/sysupgrade.conf'}
	local snapshot_seq=0
	function e.snapshot()
		local result={}
		local root='/root/.cudy-usb-backup'
		assert(e.mkdir(root) and fs.chmod(root,'700'),'备份目录创建失败')
		snapshot_seq=snapshot_seq+1
		local dir=root..'/'..os.time()..'-'..require('nixio').getpid()..'-'..snapshot_seq
		assert(not exists(dir),'备份名称已存在，拒绝覆盖')
		assert(e.mkdir(dir) and fs.chmod(dir,'700'),'备份目录权限设置失败')
		for i,path in ipairs(config_paths) do
			result[path]=read(path) or false
			if result[path] then assert(atomic(dir..'/'..i..'.conf',result[path]),'配置备份失败') end
		end
		return result
	end
	function e.restore(snap)
		for _,c in ipairs({'cudy_usb','samba4','fstab'}) do u:revert(c); u:unload(c) end
		for path,data in pairs(snap) do if data then assert(atomic(path,data)) else fs.unlink(path) end end
	end
	function e.legacy_guard(uuid)
		local data=read('/usr/libexec/tr3600-usb-share-guard') or ''
		return data:find('Reject new connections to the USB share',1,true) and data:find('/proc/mounts',1,true)
			and data:find('/sbin/block info',1,true) and data:lower():find('uuid="'..uuid..'"',1,true)
	end
	function e.clean_legacy_template()
		local path='/etc/samba/smb.conf.template'; local data=read(path)
		if not data then return false end
		local lines={}
		for line in (data..'\n'):gmatch('(.-)\n') do
			local trimmed=line:match('^%s*(.-)%s*$')
			if trimmed~='root preexec = /usr/libexec/tr3600-usb-share-guard %S' and trimmed~='root preexec close = yes'
				and trimmed~='xattr_tdb:file = /mnt/usb/.samba-metadata/xattr.tdb' then lines[#lines+1]=line end
		end
		if not atomic(path,table.concat(lines,'\n')) then return false end
		local keep='/etc/sysupgrade.conf'; local data_keep=read(keep)
		if data_keep then
			local rows={}
			for row in (data_keep..'\n'):gmatch('(.-)\n') do
				if row~='/usr/libexec/tr3600-usb-share-guard' then rows[#rows+1]=row end
			end
			if not atomic(keep,table.concat(rows,'\n')) then return false end
		end
		return true
	end
	return e
end
return M
