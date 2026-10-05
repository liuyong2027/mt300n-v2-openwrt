'use strict';
'require view';
'require fs';
'require ui';

function request(args) {
	return fs.exec('/usr/libexec/cudy-usb',args).then(function(response) {
		var data;
		try { data=JSON.parse(response.stdout || '{}'); } catch (e) { throw new Error('设备返回无效结果'); }
		if (response.code !== 0 || !data.ok) throw new Error(data.message || response.stderr || '操作失败');
		return data.result;
	});
}

return view.extend({
	load: function() { return request(['status']); },
	render: function(data) {
		var self=this;
		var volumes=Array.isArray(data.volumes) ? data.volumes : [];
		var devices=Array.isArray(data.devices) ? data.devices : [];
		function act(args) {
			ui.showModal('正在处理 USB 共享',E('p',{},'请稍候，文件共享连接可能短暂重连。'));
			return request(args).then(function(result) {
				ui.hideModal(); ui.addNotification(null,E('p',{},result.message),'info');
				return self.refresh();
			}).catch(function(error) { ui.hideModal(); ui.addNotification(null,E('p',{},error.message),'error'); });
		}
		function confirmAction(v,forget) {
			ui.showModal(forget ? '取消磁盘共享授权' : '停止共享并安全卸载',[
				E('p',{},forget ? '将停止此分区共享并卸载。此盘再次插入时不会自动共享。文件保留。' : '请先关闭此分区上的文件。卸载成功后，还需确认同一磁盘的其他分区也已卸载，才能拔出整块磁盘。'),
				E('div',{'class':'right'},[
					E('button',{'class':'btn','click':ui.hideModal},'取消'),
					E('button',{'class':'btn cbi-button-action','click':function(){ return act([forget ? 'forget' : 'eject',v.id]); }},'确认')
				])
			]);
		}
		var rows=volumes.map(function(v) {
			return E('tr',{},[
				E('td',{},v.share),E('td',{},v.uuid),E('td',{},v.target),
				E('td',{},v.ready ? '共享就绪' : '已记住授权，当前未就绪或已卸载'),
				E('td',{},v.read_only ? '访客只读' : '访客读写'),
				E('td',{},[
					E('button',{'class':'btn','click':function(){confirmAction(v,false);}},'安全卸载'),
					E('button',{'class':'btn','click':function(){confirmAction(v,true);}},'取消授权')
				])
			]);
		});
		var select=E('select',{'class':'cbi-input-select'});
		devices.forEach(function(d) {
			select.appendChild(E('option',{'value':d.uuid,'disabled':d.duplicate},
				d.device+' · '+(d.label || '无卷标')+' · '+d.fstype+' · '+d.uuid+(d.duplicate ? '（UUID 重复）' : '')));
		});
		var name=E('input',{'class':'cbi-input-text','value':'USB','maxlength':32});
		var access=E('select',{'class':'cbi-input-select'},[
			E('option',{'value':'0'},'局域网访客读写'),E('option',{'value':'1'},'局域网访客只读')
		]);
		var button=E('button',{'class':'btn cbi-button-apply','disabled':!devices.some(function(d){return !d.duplicate;}),'click':function(){
			var shared=name.value;
			if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/.test(shared) || shared.toLowerCase()==='global') {
				ui.addNotification(null,E('p',{},'共享名称限 1–32 位英文字母、数字、下划线或短横线，以字母或数字开头。'),'error'); return;
			}
			ui.showModal('启用此分区共享',[
				E('p',{},'将共享所选分区的全部文件。连接局域网的设备可免密码'+(access.value==='0' ? '读取、保存和删除文件。' : '读取文件。')+'磁盘不会被格式化。'),
				E('div',{'class':'right'},[
					E('button',{'class':'btn','click':ui.hideModal},'取消'),
					E('button',{'class':'btn cbi-button-apply','click':function(){return act(['enable',select.value,shared,access.value]);}},'启用共享')
				])
			]);
		}},'启用共享');
		var root=E('div',{},[
			E('h2',{},'USB 文件共享'),
			E('p',{},'新盘首次选择分区并启用共享；已授权分区再次插入时自动恢复。支持 FAT32、exFAT、ext4 和 NTFS，磁盘需能正常挂载。新插入的未授权磁盘不会自动共享。'),
			E('p',{},'使用 smb://'+window.location.hostname+'/共享名称 访问。本功能仅设置 Samba 局域网共享，不创建公网端口规则。'),
			E('h3',{},'当前 USB 分区'),
			E('p',{},'已经在“挂载点”页面配置的分区，请先停用原挂载配置并卸载，再使用本页。ext4 共享无需更改原文件所有者；共享服务按所选只读或读写方式访问整个分区。'),
			E('div',{'class':'cbi-value'},[E('label',{'class':'cbi-value-title'},'选择分区'),select]),
			E('div',{'class':'cbi-value'},[E('label',{'class':'cbi-value-title'},'共享名称'),name]),
			E('div',{'class':'cbi-value'},[E('label',{'class':'cbi-value-title'},'访问方式'),access]),button,
			E('h3',{},'已授权磁盘'),
			E('table',{'class':'table'},[
				E('tr',{'class':'tr table-titles'},['共享','UUID','挂载目录','状态','访问方式','操作'].map(function(x){return E('th',{},x);})),
				rows.length ? rows : E('tr',{},E('td',{'colspan':6},'尚未启用任何磁盘共享'))
			]),
			E('button',{'class':'btn','click':function(){self.refresh().catch(function(err){ui.addNotification(null,E('p',{},err.message),'error');});}},'刷新')
		]);
		this.container=E('div',{},root);
		return this.container;
	},
	refresh: function() {
		var self=this,holder=this.container;
		return this.load().then(function(next) {
			var fresh=self.render(next); holder.replaceChildren(fresh.firstChild); self.container=holder;
		});
	},
	handleSaveApply:null,handleSave:null,handleReset:null
});
