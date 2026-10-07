'use strict';
'require view';
'require rpc';
'require ui';
'require poll';

var callStatus = rpc.declare({ object: 'cudy.ss', method: 'status', expect: {} });
var callConfigure = rpc.declare({ object: 'cudy.ss', method: 'configure', params: ['enabled', 'port', 'method', 'password'], expect: {} });
var callClient = rpc.declare({ object: 'cudy.ss', method: 'client', expect: {} });
var methods = ['aes-128-gcm', 'aes-256-gcm', 'chacha20-ietf-poly1305'];
var reservedPorts = [1053, 10808, 10809, 10810, 12345];

function result(response) {
	if (!response || response.ok !== true || !response.result || typeof response.result !== 'object')
		throw new Error(response && response.message || '路由器返回无效结果');
	return response.result;
}

function message(error) {
	return error && error.message || '无法连接路由器，请稍后刷新。';
}

function passwordBytes(value) {
	var bytes = 0;
	for (var i = 0; i < value.length; i++) {
		var c = value.charCodeAt(i);
		if (c <= 0x1f || c === 0x7f) return -1;
		if (c < 0x80) bytes++;
		else if (c < 0x800) bytes += 2;
		else if (c >= 0xd800 && c <= 0xdbff) {
			var next = value.charCodeAt(++i);
			if (!(next >= 0xdc00 && next <= 0xdfff)) return -1;
			bytes += 4;
		} else if (c >= 0xdc00 && c <= 0xdfff) return -1;
		else bytes += 3;
	}
	return bytes;
}

function field(label, control, description) {
	return E('div', { 'class': 'cbi-value' }, [
		E('label', { 'class': 'cbi-value-title' }, label),
		E('div', { 'class': 'cbi-value-field' }, [control].concat(description ? [E('div', { 'class': 'cbi-value-description' }, description)] : []))
	]);
}

return view.extend({
	load: function() { return callStatus().then(result); },

	setBusy: function(busy) {
		this.busy = !!busy;
		if (!this.controls) return;
		['enabled', 'port', 'method', 'password', 'apply', 'client'].forEach(function(name) {
			this.controls[name].disabled = this.busy;
		}, this);
		this.controls.client.disabled = this.busy || !this.current.enabled || !this.current.password_set;
	},

	showStatus: function(data) {
		this.current = data;
		var state = data.applying ? '正在应用，请稍候…' : !data.enabled ? '服务已关闭' : data.ready ? '服务运行中' : !data.network_online ? '等待 ZeroTier 网络上线' : '服务尚未就绪';
		this.statusNode.replaceChildren(E('p', {}, state));
		if (data.error) this.statusNode.appendChild(E('p', { 'class': 'alert-message warning' }, String(data.error)));
		this.addressNode.replaceChildren(String(data.listen || '尚未配置'));
		this.subnetNode.replaceChildren(String(data.subnet || '尚未配置'));
		this.networkNode.replaceChildren(String(data.network_name || 'ZeroTier') + (data.network_online ? '（已连接）' : '（未连接）'));
		this.setBusy(!!data.applying);
	},

	startPolling: function() {
		if (this.pollCallback) return;
		var self = this;
		this.pollCallback = function() { return self.refreshStatus(true); };
		poll.add(this.pollCallback, 2);
	},

	stopPolling: function() {
		if (!this.pollCallback) return;
		poll.remove(this.pollCallback);
		this.pollCallback = null;
	},

	refreshStatus: function(fromPoll) {
		var self = this;
		return callStatus().then(result).then(function(data) {
			var wasApplying = self.busy;
			self.showStatus(data);
			self.lastRefreshError = null;
			if (data.applying) self.startPolling();
			else {
				self.stopPolling();
				if (wasApplying) {
					self.controls.enabled.checked = !!data.enabled;
					self.controls.port.value = String(data.port || 8388);
					self.controls.method.value = methods.indexOf(data.method) >= 0 ? data.method : methods[0];
					self.controls.password.value = '';
					if (!data.error) ui.addNotification(null, E('p', {}, '设置已应用。'), 'info');
				}
			}
			return data;
		}).catch(function(error) {
			var reason = message(error);
			if (!fromPoll || self.lastRefreshError !== reason)
				ui.addNotification(null, E('p', {}, reason), 'error');
			self.lastRefreshError = reason;
			self.statusNode.replaceChildren(E('p', { 'class': 'alert-message warning' }, '状态读取失败，请刷新重试。'));
		});
	},

	applySettings: function() {
		if (this.busy) return Promise.resolve();
		var self = this, controls = this.controls;
		var enabled = !!controls.enabled.checked;
		var rawPort = String(controls.port.value), port = Number(rawPort);
		var method = controls.method.value, password = controls.password.value;
		var byteLength = passwordBytes(password);
		var error;
		if (!/^\d+$/.test(rawPort) || port < 1024 || port > 65535 || reservedPorts.indexOf(port) >= 0)
			error = '请选择 1024–65535 之间未被其他服务占用的端口。';
		else if (methods.indexOf(method) < 0) error = '请选择支持的加密方式。';
		else if (password && (byteLength < 24 || byteLength > 128)) error = '新密码需为 24–128 字节，不能包含换行或控制字符。';
		else if (enabled && !password && !this.current.password_set) error = '首次启用时请设置 24–128 字节的密码。';
		if (error) {
			ui.addNotification(null, E('p', {}, error), 'error');
			return Promise.resolve();
		}
		this.setBusy(true);
		return callConfigure(enabled, port, method, password).then(result).then(function(data) {
			controls.password.value = '';
			if (data.applying) {
				self.statusNode.replaceChildren(E('p', {}, data.message || '正在应用，请稍候…'));
				self.startPolling();
				return self.refreshStatus(true);
			}
			return self.refreshStatus(false);
		}).catch(function(error) {
			self.setBusy(false);
			ui.addNotification(null, E('p', {}, message(error)), 'error');
		});
	},

	showClient: function() {
		if (this.busy || !this.current.enabled || !this.current.password_set) return Promise.resolve();
		var self = this;
		this.controls.client.disabled = true;
		return callClient().then(result).then(function(data) {
			ui.showModal('客户端配置', [
				E('p', {}, '对端路由器需先连接同一 ZeroTier 网络。流量跟随本路由器当前分流与代理。'),
				field('服务器', E('span', {}, String(data.server || ''))),
				field('端口', E('span', {}, String(data.port || ''))),
				field('加密方式', E('span', {}, String(data.method || ''))),
				field('密码', E('input', { 'class': 'cbi-input-text', 'type': 'text', 'readonly': true, 'value': String(data.password || '') })),
				field('导入链接', E('textarea', { 'class': 'cbi-input-textarea', 'readonly': true, 'rows': 3 }, String(data.uri || ''))),
				E('div', { 'class': 'right' }, E('button', { 'class': 'btn', 'click': ui.hideModal }, '关闭'))
			]);
		}).catch(function(error) {
			ui.addNotification(null, E('p', {}, message(error)), 'error');
		}).then(function() {
			self.controls.client.disabled = self.busy || !self.current.enabled || !self.current.password_set;
		});
	},

	render: function(data) {
		var self = this;
		this.controls = {
			enabled: E('input', { 'type': 'checkbox', 'checked': !!data.enabled }),
			port: E('input', { 'class': 'cbi-input-text', 'type': 'number', 'min': 1024, 'max': 65535, 'step': 1, 'value': String(data.port || 8388) }),
			method: E('select', { 'class': 'cbi-input-select' }, methods.map(function(name) { return E('option', { 'value': name }, name); })),
			password: E('input', { 'class': 'cbi-input-text', 'type': 'password', 'autocomplete': 'new-password', 'maxlength': 128, 'value': '' }),
			apply: E('button', { 'class': 'btn cbi-button-apply', 'click': function() { return self.applySettings(); } }, '保存并应用'),
			client: E('button', { 'class': 'btn', 'click': function() { return self.showClient(); } }, '查看客户端配置')
		};
		this.controls.method.value = methods.indexOf(data.method) >= 0 ? data.method : methods[0];
		this.statusNode = E('div', { 'class': 'cbi-section' });
		this.addressNode = E('span'); this.subnetNode = E('span'); this.networkNode = E('span');
		var root = E('div', {}, [
			E('h2', {}, 'SS 服务端'),
			E('p', {}, '让已授权的 ZeroTier 设备通过家中路由器上网，仅允许下方网段访问。'),
			this.statusNode,
			field('启用服务', this.controls.enabled),
			field('端口', this.controls.port),
			field('加密方式', this.controls.method),
			field('新密码', this.controls.password, '留空保留当前密码。建议使用 24 位以上英文字母和数字；中文字符占多个字节。'),
			field('ZeroTier 网络', this.networkNode),
			field('服务器地址', this.addressNode),
			field('允许访问的网段', this.subnetNode),
			E('div', { 'class': 'cbi-page-actions' }, [
				this.controls.apply, this.controls.client,
				E('button', { 'class': 'btn', 'click': function() { return self.refreshStatus(false); } }, '刷新状态')
			])
		]);
		this.showStatus(data);
		if (data.applying) this.startPolling();
		return root;
	},

	handleSaveApply: null, handleSave: null, handleReset: null
});
