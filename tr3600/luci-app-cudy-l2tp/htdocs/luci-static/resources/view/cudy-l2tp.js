'use strict';
'require view';
'require form';
'require uci';
'require fs';
'require ui';

function secretValid(section, value) {
	if (!value && uci.get('cudy_l2tp', section, 'enabled') !== '1') return true;
	return /^[A-Za-z0-9_@.,:+!%=-]{12,128}$/.test(value || '') ||
		'请填写 12–128 位字符，可使用字母、数字及 _ @ . , : + ! % = -';
}

return view.extend({
	render: function() {
		var m = new form.Map('cudy_l2tp', 'L2TP/IPsec VPN 服务端',
			'从外部网络连接回路由器，可访问局域网和 USB 共享。使用 IPsec 共享密钥和账号密码；启用后允许 VPN 客户端访问局域网及通过路由器上网。当前配置支持一个账号、同时一台客户端。外网连接需要公网地址或上级路由器转发 UDP 500/4500。');
		var s = m.section(form.NamedSection, 'main', 'server');
		var o = s.option(form.Flag, 'enabled', '启用服务');
		o.rmempty = false;
		o = s.option(form.Value, 'username', 'VPN 用户名');
		o.rmempty = false;
		o.validate = function(section, value) {
			return !value || /^[A-Za-z0-9_.@-]{1,64}$/.test(value) || '用户名仅限字母、数字及 _ . @ -';
		};
		o = s.option(form.Value, 'password', 'VPN 密码');
		o.password = true; o.rmempty = false; o.validate = secretValid;
		o = s.option(form.Value, 'psk', 'IPsec 共享密钥');
		o.password = true; o.rmempty = false; o.validate = secretValid;
		o = s.option(form.Value, 'subnet', 'VPN 地址段', '前三段，例如 192.168.89；必须与局域网及上级网络不同。');
		o.rmempty = false;
		o.validate = function(section, value) {
			var a = (value || '').split('.').map(Number);
			return /^\d+\.\d+\.\d+$/.test(value || '') && a.every(function(v) { return v >= 0 && v <= 255; }) &&
				(a[0] === 10 || (a[0] === 172 && a[1] >= 16 && a[1] <= 31) || (a[0] === 192 && a[1] === 168)) || '请输入私有 IPv4 地址的前三段';
		};
		o = s.option(form.Value, 'dns', '客户端 DNS');
		o.datatype = 'ip4addr'; o.rmempty = false;
		this.map = m;
		return m.render();
	},
	handleSaveApply: function() {
		return this.map.save().then(function() { return uci.apply(); }).then(function() {
			return fs.exec('/etc/init.d/cudy_l2tp', ['restart']);
		}).then(function(r) {
			ui.addNotification(null, E('p', {}, r.code === 0 ? 'VPN 配置已应用。' : '服务未启动，请检查用户名、密码、密钥及地址段是否与其他网络冲突。'), r.code === 0 ? 'info' : 'error');
		});
	}
});
