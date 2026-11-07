'use strict';
'require view';
'require form';
'require uci';
'require fs';
'require ui';

function kv(text) {
	var o = {};
	String(text || '').split(/\n/).forEach(function(line) {
		var i = line.indexOf('=');
		if (i > 0)
			o[line.slice(0, i)] = line.slice(i + 1);
	});
	return o;
}

return view.extend({
	load: function() {
		return Promise.all([
			uci.load('mango_ikev2'),
			L.resolveDefault(fs.exec_direct('/usr/libexec/mango-ikev2-lists-status'), ''),
			L.resolveDefault(fs.exec_direct('/usr/libexec/mango-ikev2-ca-status'), '')
		]);
	},

	renderLists: function(st) {
		st = st || {};
		var cnInfo = E('span', { 'id': 'mango-list-cn' }, [
			'国内 IP：' + (st.cn_lines || '0') + ' 条' +
			(st.cn_mtime && st.cn_mtime !== '-' ? '（更新于 ' + st.cn_mtime + '）' : '（尚未下载）')
		]);
		var gfwInfo = E('span', { 'id': 'mango-list-gfw' }, [
			'GFW 域名：' + (st.gfw_lines || '0') + ' 条' +
			(st.gfw_mtime && st.gfw_mtime !== '-' ? '（更新于 ' + st.gfw_mtime + '）' : '（尚未下载）')
		]);
		var result = E('pre', {
			'id': 'mango-list-result',
			'style': 'display:none;margin-top:10px;white-space:pre-wrap;max-height:160px;overflow:auto'
		});

		var refreshInfo = function() {
			return L.resolveDefault(fs.exec_direct('/usr/libexec/mango-ikev2-lists-status'), '').then(function(text) {
				var n = kv(text);
				cnInfo.textContent = '国内 IP：' + (n.cn_lines || '0') + ' 条' +
					(n.cn_mtime && n.cn_mtime !== '-' ? '（更新于 ' + n.cn_mtime + '）' : '（尚未下载）');
				gfwInfo.textContent = 'GFW 域名：' + (n.gfw_lines || '0') + ' 条' +
					(n.gfw_mtime && n.gfw_mtime !== '-' ? '（更新于 ' + n.gfw_mtime + '）' : '（尚未下载）');
			});
		};

		var runUpdate = function(script, btn, label) {
			btn.disabled = true;
			result.style.display = 'block';
			result.textContent = '正在更新' + label + '…';
			return fs.exec(script, []).then(function(res) {
				var out = ((res && res.stdout) || '') + ((res && res.stderr) || '');
				var code = res && typeof res.code === 'number' ? res.code : -1;
				if (code === 0) {
					result.textContent = out.trim() || (label + '更新成功');
					ui.addNotification(null, E('p', {}, [label + '更新成功']), 'info');
				} else {
					result.textContent = (out.trim() || (label + '更新失败')) + '\n退出码：' + code;
					ui.addNotification(null, E('p', {}, [label + '更新失败']), 'danger');
				}
				return refreshInfo();
			}).catch(function(err) {
				result.style.display = 'block';
				result.textContent = label + '更新失败：' + (err && err.message ? err.message : err);
				ui.addNotification(null, E('p', {}, [label + '更新失败']), 'danger');
			}).finally(function() {
				btn.disabled = false;
			});
		};

		var btnCn = E('button', {
			'class': 'cbi-button cbi-button-apply',
			'click': function(ev) {
				return runUpdate('/usr/libexec/mango-ikev2-cn-update', ev.currentTarget, '国内 IP');
			}
		}, ['更新国内 IP']);

		var btnGfw = E('button', {
			'class': 'cbi-button cbi-button-apply',
			'click': function(ev) {
				return runUpdate('/usr/libexec/mango-ikev2-gfw-update', ev.currentTarget, 'GFW 域名');
			}
		}, ['更新 GFW 域名']);

		return E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, ['列表更新']),
			E('div', { 'class': 'cbi-section-descr' }, [
				'国内 IP 供「大陆分流」使用；GFW 域名供「GFW 域名分流」以及大陆分流下的隧道 DNS 使用。需路由器 WAN 能直连外网以下载列表（不走 IKEv2 隧道）。'
			]),
			E('div', {
				'style': 'margin:8px 0;display:flex;flex-wrap:wrap;gap:8px 24px;align-items:center'
			}, [
				cnInfo,
				gfwInfo
			]),
			E('div', { 'style': 'margin-top:10px;display:flex;gap:8px;flex-wrap:wrap' }, [
				btnCn, btnGfw
			]),
			result
		]);
	},

	renderCa: function(st) {
		st = st || {};
		var info = E('pre', {
			'id': 'mango-ca-info',
			'style': 'margin:8px 0;white-space:pre-wrap;max-height:180px;overflow:auto'
		});
		var result = E('pre', {
			'id': 'mango-ca-result',
			'style': 'display:none;margin-top:10px;white-space:pre-wrap;max-height:160px;overflow:auto'
		});
		var formatInfo = function(n) {
			n = n || {};
			var lines = [
				'安装路径：' + (n.path || '/etc/swanctl/x509ca/nordvpn-root-ca.pem'),
				'兼容路径：' + (n.path_legacy || '/etc/ipsec.d/cacerts/nordvpn-root-ca.pem'),
				'文件：' + (n.present === '1'
					? ('已安装，' + (n.size || '?') + ' 字节' +
						(n.mtime && n.mtime !== '-' ? '，更新于 ' + n.mtime : ''))
					: '未安装'),
				'兼容副本：' + (n.legacy_present === '1' ? '存在' : '缺失'),
				'strongSwan：' + (n.loaded === '1' ? '已加载' : '未加载'),
				'主题：' + (n.subject || '-'),
				'有效期至：' + (n.not_after || '-')
			];
			info.textContent = lines.join('\n');
		};

		formatInfo(st);

		var refresh = function() {
			return L.resolveDefault(fs.exec_direct('/usr/libexec/mango-ikev2-ca-status'), '').then(function(text) {
				formatInfo(kv(text));
			});
		};

		var runInstall = function(btn, srcPath) {
			btn.disabled = true;
			result.style.display = 'block';
			result.textContent = '正在安装根证书…';
			return fs.exec('/usr/libexec/mango-ikev2-ca-install', [srcPath]).then(function(res) {
				var out = ((res && res.stdout) || '') + ((res && res.stderr) || '');
				var code = res && typeof res.code === 'number' ? res.code : -1;
				if (code === 0) {
					result.textContent = out.trim() || '安装成功';
					ui.addNotification(null, E('p', {}, ['根证书安装成功']), 'info');
				} else {
					result.textContent = (out.trim() || '安装失败') + '\n退出码：' + code;
					ui.addNotification(null, E('p', {}, ['根证书安装失败']), 'danger');
				}
				return refresh();
			}).catch(function(err) {
				result.style.display = 'block';
				result.textContent = '安装失败：' + (err && err.message ? err.message : err);
				ui.addNotification(null, E('p', {}, ['根证书安装失败']), 'danger');
			}).finally(function() {
				btn.disabled = false;
			});
		};

		var btnUpload = E('button', {
			'class': 'cbi-button cbi-button-apply',
			'click': function(ev) {
				var btn = ev.currentTarget;
				btn.disabled = true;
				result.style.display = 'block';
				result.textContent = '请选择 PEM/CRT 文件…';
				// ui.uploadFile always shows LuCI's own picker; do not add a second page-level file input.
				return ui.uploadFile('/tmp/mango-ikev2-upload-ca.pem').then(function() {
					return runInstall(btn, '/tmp/mango-ikev2-upload-ca.pem');
				}).catch(function(err) {
					result.textContent = '上传失败：' + (err && err.message ? err.message : err);
					ui.addNotification(null, E('p', {}, ['上传失败']), 'danger');
					btn.disabled = false;
				});
			}
		}, ['上传并安装']);

		var btnRefresh = E('button', {
			'class': 'cbi-button',
			'click': function(ev) {
				var btn = ev.currentTarget;
				btn.disabled = true;
				return refresh().finally(function() { btn.disabled = false; });
			}
		}, ['刷新状态']);

		return E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, ['根证书']),
			E('div', { 'class': 'cbi-section-descr' }, [
				'NordVPN IKEv2 需要根 CA。支持 PEM 文本，或 NordVPN 常见的 DER/CRT 二进制；安装后写入 swanctl，并同步到 ipsec.d，随后尝试 reload strongSwan 凭据。'
			]),
			info,
			E('div', { 'style': 'margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center' }, [
				btnUpload, btnRefresh
			]),
			result
		]);
	},

	handleSaveApply: function(ev, mode) {
		// This LuCI build does not reload mango_ikev2 from ucitrack.
		// Commit first, then reload so the saved mode actually takes effect.
		return this.handleSave(ev).then(function() {
			return ui.changes.apply(mode == '0');
		}).then(function() {
			return fs.exec('/etc/init.d/mango_ikev2', ['reload']);
		});
	},

	render: function(data) {
		var listStatus = kv(data[1]);
		var caStatus = kv(data[2]);
		var m = new form.Map('mango_ikev2', 'IKEv2 客户端',
			'本镜像以 strongSwan 做路由器级 IKEv2 客户端。与 SSR Plus+ 运行时互斥：启用 IKEv2 会停止 SSR Plus+ 客户端。' +
			'启用后局域网 DNS 改由本机 dnsmasq 回答。' +
			'大陆分流：国内 IP 直连，其余走隧道；DNS 默认国内，GFW 域名走隧道 DNS。' +
			'GFW 模式：仅列表域名走隧道。全局：全部走隧道。');

		var s = m.section(form.NamedSection, 'main', 'policy', '连接与分流');
		s.anonymous = true;

		var o = s.option(form.Flag, 'enabled', '启用 IKEv2 客户端');
		o.rmempty = false;

		o = s.option(form.ListValue, 'mode', '分流模式');
		o.value('direct', '全部直连（不经隧道）');
		o.value('split', '大陆分流（国内 IP 直连，其余 IKEv2）');
		o.value('gfw', 'GFW 域名分流（仅列表内域名走 IKEv2）');
		o.value('global', '全局隧道');
		o.rmempty = false;

		o = s.option(form.Value, 'server', '服务器地址');
		o.datatype = 'host';
		o.rmempty = false;
		o = s.option(form.Value, 'remote_id', '远端 ID', '可留空，默认与服务器地址相同；NordVPN 建议填主机名');
		o.placeholder = 'vpn.example.com';

		o = s.option(form.Value, 'server2', '备用服务器1', '留空则跳过。主用连续两次失败后按 备用1 → 备用2 → 主用 轮换。');
		o.datatype = 'host';
		o.rmempty = true;
		o = s.option(form.Value, 'remote_id2', '备用1 远端 ID', '可留空，默认与备用服务器1地址相同');
		o.rmempty = true;

		o = s.option(form.ListValue, 'auth2', '备用1 认证', '留空则使用主服务器的认证方式。');
		o.value('', '与主服务器相同');
		o.value('eap', '另一套 EAP 用户名密码');
		o.value('psk', '另一套预共享密钥');
		o.rmempty = true;
		o = s.option(form.Value, 'username2', '备用1 用户名');
		o.depends('auth2', 'eap');
		o = s.option(form.Value, 'password2', '备用1 密码');
		o.password = true;
		o.depends('auth2', 'eap');
		o = s.option(form.Value, 'psk2', '备用1 预共享密钥');
		o.password = true;
		o.depends('auth2', 'psk');
		o = s.option(form.Value, 'local_id2', '备用1 本端 ID', '留空时，EAP 用备用1用户名，PSK 用 %any');
		o.depends('auth2', 'eap');
		o.depends('auth2', 'psk');

		o = s.option(form.Value, 'server3', '备用服务器2', '第二备用，留空则只有主用/备用1参与轮换。');
		o.datatype = 'host';
		o.rmempty = true;
		o = s.option(form.Value, 'remote_id3', '备用2 远端 ID', '可留空，默认与备用服务器2地址相同');
		o.rmempty = true;
		o = s.option(form.ListValue, 'auth3', '备用2 认证', '留空则使用主服务器的认证方式。');
		o.value('', '与主服务器相同');
		o.value('eap', '另一套 EAP 用户名密码');
		o.value('psk', '另一套预共享密钥');
		o.rmempty = true;
		o = s.option(form.Value, 'username3', '备用2 用户名');
		o.depends('auth3', 'eap');
		o = s.option(form.Value, 'password3', '备用2 密码');
		o.password = true;
		o.depends('auth3', 'eap');
		o = s.option(form.Value, 'psk3', '备用2 预共享密钥');
		o.password = true;
		o.depends('auth3', 'psk');
		o = s.option(form.Value, 'local_id3', '备用2 本端 ID', '留空时，EAP 用备用2用户名，PSK 用 %any');
		o.depends('auth3', 'eap');
		o.depends('auth3', 'psk');

		o = s.option(form.ListValue, 'auth', '认证方式');
		o.value('eap', 'EAP-MSCHAPv2（用户名密码）');
		o.value('psk', '预共享密钥 PSK');
		o.rmempty = false;
		o = s.option(form.Value, 'username', '用户名');
		o.depends('auth', 'eap');
		o = s.option(form.Value, 'password', '密码');
		o.password = true;
		o.depends('auth', 'eap');
		o = s.option(form.Value, 'psk', '预共享密钥');
		o.password = true;
		o.depends('auth', 'psk');
		o = s.option(form.Value, 'local_id', '本端 ID', 'NordVPN IKEv2 请留空；PSK 可填 %any');

		o = s.option(form.Value, 'lan_device', 'LAN 设备', '可填多个，空格分隔，例如：br-lan ztc3q2tbgr。这些接口的流量会参与分流/代理。');
		o.default = 'br-lan';
		o.rmempty = false;
		o = s.option(form.Value, 'ifid', 'XFRM if_id');
		o.datatype = 'uinteger';
		o.default = '42';
		o.rmempty = false;
		o = s.option(form.Value, 'xfrm_mtu', 'XFRM MTU');
		o.datatype = 'range(1280,1500)';
		o.default = '1280';
		o.rmempty = false;

		return m.render().then(L.bind(function(node) {
			return E('div', {}, [
				node,
				this.renderCa(caStatus),
				this.renderLists(listStatus)
			]);
		}, this));
	}
});
