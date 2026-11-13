'use strict';
'require view';
'require fs';
'require poll';
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

function parseProbes(text) {
	var blocks = String(text || '').split(/^---$/m);
	var map = {};
	blocks.forEach(function(block) {
		var p = kv(block);
		if (p.target)
			map[p.target] = p;
	});
	return map;
}

function fmtAgo(sec) {
	sec = parseInt(sec, 10);
	if (!sec && sec !== 0)
		return '-';
	if (sec < 60)
		return sec + ' 秒';
	if (sec < 3600)
		return Math.floor(sec / 60) + ' 分钟';
	return Math.floor(sec / 3600) + ' 小时 ' + Math.floor((sec % 3600) / 60) + ' 分钟';
}

function peerLabel(p) {
	if (p === 'mango3' || p === '备用服务器2')
		return '备用服务器2';
	if (p === 'mango2' || p === '备用服务器1' || p === '备用服务器')
		return '备用服务器1';
	if (p === 'mango' || p === '主服务器')
		return '主服务器';
	return p || '-';
}

function resultLabel(r) {
	return ({
		ok: '成功',
		warn: '警告',
		fail: '失败',
		switch: '节点切换',
		down: '断开'
	})[r] || r;
}

function resultClass(r) {
	return ({
		ok: 'notice',
		warn: 'warning',
		fail: 'danger',
		switch: 'warning',
		down: 'warning'
	})[r] || '';
}

function probeLabel(p) {
	if (!p)
		return '未测试';
	if (p.ok === '1')
		return '通 (' + (p.ms || '?') + ' ms, HTTP ' + (p.http || '?') + ', ' + (p.via || '?') + ')';
	return '不通 (HTTP ' + (p.http || '0') + ', ' + (p.via || '?') + ')';
}

function probeClass(p) {
	if (!p)
		return '';
	return p.ok === '1' ? 'notice' : 'danger';
}

return view.extend({
	load: function() {
		return Promise.all([
			L.resolveDefault(fs.exec_direct('/usr/libexec/mango-ikev2-status'), ''),
			L.resolveDefault(fs.read('/var/log/mango-ikev2-events.log'), '')
		]);
	},

	renderStatus: function(st) {
		var up = st.state === 'up';
		return E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, ['当前连接']),
			E('div', { 'class': 'table' }, [
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left', 'width': '30%' }, ['状态']),
					E('div', { 'class': 'td left' }, [
						E('span', { 'class': 'label ' + (up ? 'notice' : 'danger') }, [up ? '已连通' : '未连通'])
					])
				]),
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left' }, ['节点']),
					E('div', { 'class': 'td left' }, [peerLabel(st.peer) + (st.remote_id ? ' / ' + st.remote_id : '')])
				]),
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left' }, ['服务器']),
					E('div', { 'class': 'td left' }, [st.server || '-'])
				]),
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left' }, ['虚拟 IP']),
					E('div', { 'class': 'td left' }, [st.vip || '-'])
				]),
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left' }, ['已连接时长']),
					E('div', { 'class': 'td left' }, [fmtAgo(st.established_s)])
				]),
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left' }, ['最近成功']),
					E('div', { 'class': 'td left' }, [st.last_ok || '-'])
				]),
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left' }, ['最近失败']),
					E('div', { 'class': 'td left' }, [st.last_fail || '-'])
				]),
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left' }, ['最近节点切换']),
					E('div', { 'class': 'td left' }, [
						st.last_switch
							? (st.last_switch + (st.last_switch_detail ? '（' + st.last_switch_detail + '）' : ''))
							: '-'
					])
				]),
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left' }, ['模式']),
					E('div', { 'class': 'td left' }, [(st.enabled === '1' ? '' : '未启用 / ') + (st.mode || '-')])
				])
			])
		]);
	},

	renderProbe: function(probes) {
		probes = probes || {};
		var baiduCell = E('span', { 'id': 'probe-baidu', 'class': 'label ' + probeClass(probes.baidu) }, [probeLabel(probes.baidu)]);
		var googleCell = E('span', { 'id': 'probe-google', 'class': 'label ' + probeClass(probes.google) }, [probeLabel(probes.google)]);
		var self = this;

		var run = function(target, btn) {
			btn.disabled = true;
			baiduCell.textContent = target === 'google' ? baiduCell.textContent : '测试中…';
			googleCell.textContent = target === 'baidu' ? googleCell.textContent : '测试中…';
			if (target !== 'google')
				baiduCell.className = 'label';
			if (target !== 'baidu')
				googleCell.className = 'label';

			return fs.exec('/usr/libexec/mango-ikev2-probe', [target]).then(function(res) {
				var map = parseProbes((res && res.stdout) || '');
				if (map.baidu) {
					baiduCell.className = 'label ' + probeClass(map.baidu);
					baiduCell.textContent = probeLabel(map.baidu);
				}
				if (map.google) {
					googleCell.className = 'label ' + probeClass(map.google);
					googleCell.textContent = probeLabel(map.google);
				}
				if (!map.baidu && !map.google) {
					ui.addNotification(null, E('p', {}, ['连通性测试失败：无输出']), 'danger');
				}
			}).catch(function(err) {
				ui.addNotification(null, E('p', {}, ['连通性测试失败：' + (err && err.message ? err.message : err)]), 'danger');
			}).finally(function() {
				btn.disabled = false;
			});
		};

		var btnBaidu = E('button', {
			'class': 'cbi-button cbi-button-action',
			'click': function(ev) { run('baidu', ev.currentTarget); }
		}, ['测试百度']);

		var btnGoogle = E('button', {
			'class': 'cbi-button cbi-button-action',
			'click': function(ev) { run('google', ev.currentTarget); }
		}, ['测试 Google']);

		var btnAll = E('button', {
			'class': 'cbi-button cbi-button-apply',
			'click': function(ev) { run('all', ev.currentTarget); }
		}, ['全部测试']);

		return E('div', { 'class': 'cbi-section', 'id': 'mango-ikev2-probe' }, [
			E('h3', {}, ['连通性测试']),
			E('div', { 'class': 'cbi-section-descr' }, ['百度走直连，Google 走隧道，用于确认大陆分流是否正常。']),
			E('div', { 'class': 'table' }, [
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left', 'width': '30%' }, ['百度']),
					E('div', { 'class': 'td left' }, [baiduCell])
				]),
				E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td left' }, ['Google']),
					E('div', { 'class': 'td left' }, [googleCell])
				])
			]),
			E('div', { 'style': 'margin-top:10px; display:flex; gap:8px; flex-wrap:wrap' }, [
				btnBaidu, btnGoogle, btnAll
			])
		]);
	},

	renderEvents: function(text) {
		var lines = String(text || '').trim().split(/\n/).filter(Boolean).reverse().slice(0, 20);
		var rows = [
			E('div', { 'class': 'tr cbi-section-table-titles' }, [
				E('div', { 'class': 'th' }, ['时间']),
				E('div', { 'class': 'th' }, ['结果']),
				E('div', { 'class': 'th' }, ['节点']),
				E('div', { 'class': 'th' }, ['服务器']),
				E('div', { 'class': 'th' }, ['远端 ID']),
				E('div', { 'class': 'th' }, ['说明'])
			])
		];

		if (!lines.length) {
			rows.push(E('div', { 'class': 'tr' }, [
				E('div', { 'class': 'td' }, ['暂无连接事件'])
			]));
		} else {
			lines.forEach(function(line) {
				var p = line.split(/\t/);
				rows.push(E('div', { 'class': 'tr' }, [
					E('div', { 'class': 'td' }, [p[0] || '']),
					E('div', { 'class': 'td' }, [
						E('span', { 'class': 'label ' + resultClass(p[1]) }, [resultLabel(p[1])])
					]),
					E('div', { 'class': 'td' }, [peerLabel(p[2])]),
					E('div', { 'class': 'td' }, [p[3] || '']),
					E('div', { 'class': 'td' }, [p[4] || '']),
					E('div', { 'class': 'td' }, [p[5] || ''])
				]));
			});
		}

		return E('div', { 'class': 'cbi-section' }, [
			E('h3', {}, ['连接记录']),
			E('div', { 'class': 'cbi-section-descr' }, ['记录连通成功、探测警告、失败与节点切换（含时间），不含 strongSwan 明细。']),
			E('div', { 'class': 'table cbi-section-table' }, rows)
		]);
	},

	render: function(data) {
		var self = this;
		var st = kv(data[0]);
		var probeBox = this.renderProbe({});
		var eventsBox = this.renderEvents(data[1]);
		var statusBox = this.renderStatus(st);
		var root = E('div', { 'id': 'mango-ikev2-log' }, [
			E('h2', {}, ['IKEv2 日志']),
			statusBox,
			probeBox,
			eventsBox
		]);

		poll.add(L.bind(function() {
			return Promise.all([
				L.resolveDefault(fs.exec_direct('/usr/libexec/mango-ikev2-status'), ''),
				L.resolveDefault(fs.read('/var/log/mango-ikev2-events.log'), '')
			]).then(L.bind(function(next) {
				var box = document.getElementById('mango-ikev2-log');
				if (!box)
					return;
				/* Keep probe results: only refresh status + events. */
				var oldProbe = document.getElementById('mango-ikev2-probe');
				var freshStatus = this.renderStatus(kv(next[0]));
				var freshEvents = this.renderEvents(next[1]);
				var children = box.childNodes;
				/* structure: h2, status, probe, events */
				if (children.length >= 4) {
					box.replaceChild(freshStatus, children[1]);
					box.replaceChild(freshEvents, children[3]);
				}
			}, this));
		}, this), 10);

		return root;
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
