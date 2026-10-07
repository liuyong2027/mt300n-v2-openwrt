'use strict';
'require view';
'require form';
'require uci';
'require fs';
'require ui';

return view.extend({
	load: function() { return Promise.all([uci.load('wireless'),uci.load('cudy_wifi')]); },
	render: function() {
		var m = new form.Map('cudy_wifi','Wi-Fi 双频合一',
			'统一 2.4 GHz 和 5 GHz 的无线名称、密码及加密方式。频段引导可建议支持的终端在信号较好时连接 5 GHz，实际选择仍取决于终端。启用前，请在“无线”页面配置国家并启用两个局域网接入点。应用时无线会短暂重连；关闭合一后恢复启用前的两个网络。合一期间请在本页调整共同设置。');
		var s = m.section(form.NamedSection,'main','wifi');
		var o = s.option(form.Flag,'enabled','启用双频合一');
		o.rmempty = false;
		var aps = {'2g':[], '5g':[]};
		uci.sections('wireless','wifi-iface',function(ap) {
			var network = ap.network;
			if (ap.mode !== 'ap' || !(network === 'lan' || (Array.isArray(network) && network.length === 1 && network[0] === 'lan'))) return;
			var band = uci.get('wireless',ap.device,'band');
			if (aps[band]) aps[band].push(ap);
		});
		['2g','5g'].forEach(function(band) {
			var option = s.option(form.ListValue,band === '2g' ? 'ap2g' : 'ap5g',band === '2g' ? '2.4 GHz 接入点' : '5 GHz 接入点');
			aps[band].forEach(function(ap) { option.value(ap['.name'],(ap.ssid || '未命名')+' ('+ap['.name']+')'); });
			if (aps[band].length === 1) option.default = aps[band][0]['.name'];
			option.depends('enabled','1'); option.rmempty = false;
		});
		o = s.option(form.Value,'ssid','共同无线名称');
		o.depends('enabled','1'); o.rmempty = false;
		if (aps['5g'].length === 1) o.default = aps['5g'][0].ssid;
		o.validate = function(section,value) {
			try { return value && unescape(encodeURIComponent(value)).length <= 32 && !/[\x00-\x1f\x7f]/.test(value) || '无线名称须为 1–32 字节，不能包含控制字符'; }
			catch (e) { return '无线名称格式无效'; }
		};
		o = s.option(form.ListValue,'encryption','共同加密方式');
		o.value('sae-mixed','WPA2 / WPA3 兼容模式'); o.value('psk2','WPA2-PSK'); o.value('sae','WPA3-SAE');
		o.default = 'sae-mixed'; o.rmempty = false; o.depends('enabled','1');
		o = s.option(form.Value,'key','共同无线密码','留空沿用所选 5 GHz 网络当前密码。');
		o.password = true; o.depends('enabled','1');
		o.validate = function(section,value) { return !value || /^[\x20-\x7e]{8,63}$/.test(value) || '请输入 8–63 位可打印英文字符密码'; };
		o = s.option(form.Flag,'steering','自动频段引导','仅在信号足够时建议支持的设备切换至 5 GHz；关闭后仍保持同名双频网络，由终端自行选择。');
		o.default = '1'; o.rmempty = false; o.depends('enabled','1');
		this.map = m;
		return m.render();
	},
	handleSaveApply: function() {
		return this.map.save().then(function() { return uci.apply(); }).then(function() {
			return fs.exec('/usr/libexec/cudy-wifi-apply',['apply']);
		}).then(function(result) {
			ui.addNotification(null,E('p',{},result.stdout || result.stderr || '请重新连接无线并检查配置状态。'),result.code === 0 ? 'info' : 'error');
		});
	}
});
