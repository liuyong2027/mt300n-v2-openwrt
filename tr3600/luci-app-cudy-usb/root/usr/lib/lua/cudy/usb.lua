-- Disk consent and lifecycle policy. All OS effects are injected for testing.
local M = {}
local types = {vfat='vfat',exfat='exfat',ext4='ext4',ntfs='ntfs3',ntfs3='ntfs3'}
local function fail(message) error(message,0) end
function M.uuid(value)
	return type(value)=='string' and #value<=64 and #value>=4 and value:match('^[%w%-]+$') and value:lower() or nil
end
function M.id(uuid) return 'usb_'..assert(M.uuid(uuid)):gsub('%-','_') end
function M.share(value)
	return type(value)=='string' and #value<=32 and value:match('^[%a%d][%w_%-]*$') and value:lower()~='global'
end
function M.target(value)
	return value=='/mnt/usb' or (type(value)=='string' and value:match('^/mnt/cudy%-usb/usb_[%w_]+$')~=nil)
end
local function volume(u,id)
	local v=u:get_all('cudy_usb',id)
	if not v or v['.type']~='volume' or M.id(v.uuid or '')~=id or not M.target(v.target) or not M.share(v.share) or not types[v.fstype] then
		fail('磁盘授权配置无效')
	end
	v.id=id; return v
end
function M.devices(e)
	local rows, counts = {}, {}
	for _,d in ipairs(e.devices()) do
		if d.device:match('^/dev/sd%l+%d*$') and e.is_usb(d.device) and M.uuid(d.uuid) and types[d.fstype] then
			d.uuid=M.uuid(d.uuid); rows[#rows+1]=d; counts[d.uuid]=(counts[d.uuid] or 0)+1
		end
	end
	for _,d in ipairs(rows) do d.duplicate=counts[d.uuid]>1 end
	return rows
end
local function find(e,uuid)
	local selected
	for _,d in ipairs(M.devices(e)) do
		if d.uuid==uuid then
			if d.duplicate then fail('检测到重复 UUID，拒绝共享，请先移除重复磁盘') end
			selected=d
		end
	end
	return selected
end
local function mounted(e,v,d)
	if not d then return false end
	local m=e.mount_at(v.target)
	return m and m.device==d.device and e.realpath(v.target)==v.target and
		(types[m.fstype] or m.fstype)==types[v.fstype] and
		(v.read_only=='1' or m.rw) and not e.is_link(v.target)
end
local function metadata(e,v)
	local dir=v.target..'/.samba-metadata'
	if e.is_link(dir) or e.is_link(dir..'/xattr.tdb') then fail('元数据目录或数据库是符号链接，拒绝共享') end
	if v.read_only=='1' then
		-- Read-only volumes need no writable xattr database.
		return true
	end
	if not e.mkdir(dir) or e.realpath(dir)~=dir then fail('无法建立共享元数据目录') end
	return true
end
function M.guard(u,e,id,requested_target)
	local v=volume(u,id)
	if not e.lan_only() then fail('Samba 未仅绑定局域网，拒绝共享') end
	if requested_target and requested_target~=v.target then fail('共享路径与授权挂载路径不一致') end
	if v.enabled~='1' or e.ejected(id) then fail('该磁盘共享已停止') end
	local d=find(e,v.uuid)
	if not mounted(e,v,d) then fail('指定 USB 分区未正确挂载，拒绝访问内部目录') end
	metadata(e,v)
	return v,d
end
local function share_section(u,e,v)
	local id=v.id
	u:delete('samba4',id)
	u:set('samba4',id,'sambashare')
	local values={name=v.share,path=v.target,browseable='yes',read_only=v.read_only=='1' and 'yes' or 'no',
		guest_ok='yes',guest_only='yes',force_root='1',create_mask='0666',dir_mask='0777',cudy_usb=id,
		vfs_objects=v.read_only=='1' and 'catia fruit streams_xattr' or 'catia fruit streams_xattr xattr_tdb'}
	for k,x in pairs(values) do u:set('samba4',id,k,x) end
end
local function commit(u,e,configs)
	for _,c in ipairs(configs) do if not u:commit(c) then fail('保存配置失败：'..c) end end
	if not e.restart() then fail('文件共享服务启动失败') end
end
local function conflict(u,id,d,target,name)
	u:foreach('samba4','sambashare',function(s)
		if s['.name']~=id and (s.name or ''):lower()==name:lower() then fail('共享名称已被使用') end
	end)
	u:foreach('fstab','mount',function(s)
		if s.enabled~='0' and (M.uuid(s.uuid)==d.uuid or s.target==target) then fail('此分区已有挂载配置，请先在挂载点页面停用或移除该项') end
	end)
end
function M.enable(u,e,uuid,name,readonly)
	uuid=M.uuid(uuid); if not uuid or not M.share(name) or (readonly~='0' and readonly~='1') then fail('请选择有效分区、共享名和访问方式') end
	if not e.lan_only() then fail('请先在网络共享设置中仅绑定 lan，并使用标准 Samba 配置') end
	local d=find(e,uuid); if not d then fail('USB 分区已移除或文件系统不支持') end
	local id=M.id(uuid); local existing=u:get_all('cudy_usb',id)
	local target=existing and existing.target or '/mnt/cudy-usb/'..id
	if not M.target(target) then fail('挂载路径无效') end
	conflict(u,id,d,target,name)
	if d.mount and d.mount~='' and d.mount~=target then fail('此分区已挂载到其他位置，请先卸载再启用共享') end
	local at=e.mount_at(target)
	if at and at.device~=d.device then fail('挂载目录已被其他磁盘占用') end
	if at and not existing then fail('已有非本功能管理的挂载，请先卸载') end
	if existing and (existing.fstype~=d.fstype or existing.read_only~=readonly) and at then fail('更改访问方式前请先安全卸载该分区') end
	local snap=e.snapshot(); local did_mount=false; local was_ejected=e.ejected(id)
	local ok,err=pcall(function()
		if not e.mkdir_target(target) then fail('挂载目录不安全或创建失败') end
		if not at then
			if not e.mount(d.device,target,types[d.fstype],readonly,d.fstype) then fail('磁盘挂载失败；未格式化或修复磁盘') end
			did_mount=true
		end
		u:set('cudy_usb',id,'volume')
		local v={id=id,uuid=uuid,share=name,target=target,fstype=d.fstype,read_only=readonly,enabled='1'}
		for k,x in pairs(v) do if k~='id' then u:set('cudy_usb',id,k,x) end end
		e.mark_ejected(id,false)
		if not mounted(e,v,d) then fail('挂载结果与分区不匹配') end
		metadata(e,v); share_section(u,e,v)
		commit(u,e,{'cudy_usb','samba4'})
	end)
	if not ok then
		e.restore(snap); e.mark_ejected(id,was_ejected); if did_mount then e.unmount(target) end; e.restart(); fail(tostring(err))
	end
	return {message='共享已启用，局域网设备可免密码访问 '..name,id=id}
end
function M.reconcile(u,e)
	local changed=false; local errors={}
	u:foreach('cudy_usb','volume',function(s)
		local id=s['.name']
		local ok,err=pcall(function()
			if not e.lan_only() then fail('Samba 未仅绑定局域网，停止自动共享') end
			local v=volume(u,id); local d=find(e,v.uuid)
			if v.enabled~='1' or e.ejected(id) or not d then
				if u:get('samba4',id)=='sambashare' then u:delete('samba4',id); changed=true end
				return
			end
			local at=e.mount_at(v.target)
			if not at then
				if d.mount and d.mount~='' then fail('已授权分区挂载在其他位置') end
				if not e.mkdir_target(v.target) or not e.mount(d.device,v.target,types[v.fstype],v.read_only,v.fstype) then fail('已授权分区自动挂载失败') end
			end
			M.guard(u,e,id)
			local share=u:get_all('samba4',id)
			if not share or share.path~=v.target or share.name~=v.share or share.cudy_usb~=id then share_section(u,e,v); changed=true end
		end)
		if not ok then
			if u:get('samba4',id)=='sambashare' then u:delete('samba4',id); changed=true end
			errors[#errors+1]={id=id,message=tostring(err)}
		end
	end)
	if changed then commit(u,e,{'samba4'}) end
	return {message='已检查授权磁盘',errors=errors}
end
function M.eject(u,e,id,forget)
	local v=volume(u,id); local snap=e.snapshot(); local was_ejected=e.ejected(id)
	e.mark_ejected(id,true)
	u:delete('samba4',id)
	local ok,err=pcall(function()
		commit(u,e,{'samba4'})
		if not e.sync() then fail('写入同步失败，不能安全拔盘') end
		local at=e.mount_at(v.target)
		if at then
			local d=find(e,v.uuid)
			if not mounted(e,v,d) then fail('目录被其他磁盘占用，拒绝卸载') end
			if not e.unmount(v.target) or e.mount_at(v.target) then fail('分区仍在使用，卸载失败；请关闭文件后重试') end
		end
		if forget then u:delete('cudy_usb',id); if not u:commit('cudy_usb') then fail('删除授权失败') end end
	end)
	if not ok then e.restore(snap); e.mark_ejected(id,was_ejected); e.restart(); fail(tostring(err)) end
	return {message=forget and '共享授权已取消；重新插入不会自动共享' or '此分区已停止共享并卸载；同一磁盘的其他分区也需卸载后才能拔盘'}
end
function M.status(u,e)
	local devices=M.devices(e); local volumes={}
	u:foreach('cudy_usb','volume',function(v)
		local row={id=v['.name'],uuid=v.uuid,share=v.share,target=v.target,read_only=v.read_only=='1',enabled=v.enabled=='1'}
		local ok=pcall(function()
			local v=volume(u,row.id); local d=find(e,v.uuid)
			if not e.lan_only() or v.enabled~='1' or e.ejected(row.id) or not mounted(e,v,d) then fail('尚未就绪') end
			if v.read_only~='1' and not e.metadata_exists(v.target) then fail('元数据尚未就绪') end
		end)
		row.ready=ok
		volumes[#volumes+1]=row
	end)
	return {devices=devices,volumes=volumes}
end
-- Upgrade adoption is narrow: only the old project-owned USB setup is migrated.
function M.migrate(u,e)
	if u:get('cudy_usb','main','migrated')=='1' then return {message='迁移已完成'} end
	local old=u:get_all('fstab','tr3600_usb'); local s=u:get_all('samba4','usb')
	local uuid=old and M.uuid(old.uuid)
	if not (uuid and old.target=='/mnt/usb' and old.fstype=='vfat' and old.enabled=='1' and s and s.path=='/mnt/usb' and s.name=='USB' and s.guest_ok=='yes' and s.guest_only=='yes' and s.read_only=='no' and e.legacy_guard(uuid)) then
		return {message='没有需要迁移的旧 USB 共享'}
	end
	local snap=e.snapshot(true)
	local ok,err=pcall(function()
		if not e.lan_only() then fail('旧共享未仅绑定局域网，拒绝自动迁移') end
		local id=M.id(uuid)
		if u:get('cudy_usb',id) then fail('旧盘授权与新配置冲突') end
		if not e.clean_legacy_template() then fail('旧共享模板迁移失败') end
		u:set('cudy_usb',id,'volume')
		for k,x in pairs({uuid=uuid,share='USB',target='/mnt/usb',fstype='vfat',read_only='0',enabled='1'}) do u:set('cudy_usb',id,k,x) end
		u:delete('fstab','tr3600_usb'); u:delete('samba4','usb')
		u:set('cudy_usb','main','migrated','1')
		commit(u,e,{'fstab','samba4','cudy_usb'})
	end)
	if not ok then e.restore(snap); e.restart(); fail(tostring(err)) end
	return M.reconcile(u,e)
end
return M
