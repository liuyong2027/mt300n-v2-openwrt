'use strict';
'require view';
'require form';
'require uci';
'require fs';
'require ui';

return view.extend({
	load: function() { return uci.load('cudy_led'); },
	render: function() {
		var m = new form.Map('cudy_led','指示灯',
			'白灯常亮表示近期连通性检查通过；白灯慢闪表示正在等待确认；红灯常亮表示出口离线，红灯慢闪表示网络或代理连续失败。状态不代表网速或所有网站均可访问。启动、升级和救援提示始终由系统管理。');
		var s = m.section(form.NamedSection,'main','led');
		var o = s.option(form.ListValue,'mode','灯光模式');
		o.value('status','状态提示（推荐）'); o.value('default','恢复原有系统灯光'); o.value('off','关闭日常灯光');
		o.default='status'; o.rmempty=false;
		o = s.option(form.Flag,'night','夜间关闭白灯','故障红灯仍保留；仅在时钟已同步时按时间关灯。');
		o.default='0'; o.rmempty=false; o.depends('mode','status');
		['night_start','night_end'].forEach(function(name) {
			var option=s.option(form.Value,name,name === 'night_start' ? '夜间开始' : '夜间结束','路由器本地时间，格式 HH:MM。');
			option.default=name === 'night_start' ? '23:00' : '07:00'; option.rmempty=false;
			option.depends({mode:'status',night:'1'});
			option.validate=function(section,value) {
				if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)) return '请输入有效时间，例如 23:00';
				var other=this.map.lookupOption(name === 'night_start' ? 'night_end' : 'night_start',section)[0];
				return !other || other.formvalue(section) !== value || '开始和结束时间不能相同';
			};
		});
		this.map=m; return m.render();
	},
	handleSaveApply: function() {
		return this.map.save().then(function() { return uci.apply(); }).then(function() {
			return fs.exec('/usr/libexec/cudy-led-apply',[]);
		}).then(function(result) {
			ui.addNotification(null,E('p',{},result.stdout || result.stderr || '请检查指示灯服务状态'),result.code === 0 ? 'info' : 'error');
		});
	}
});
