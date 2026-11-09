'use strict';
const assert = require('assert');
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const test = require('node:test');
const vm = require('vm');

const root = __dirname;
const VAR_LOG = '/var/log/mango-ikev2-events.log';
const TMP_LOG = '/tmp/log/mango-ikev2-events.log';
const aclPath = path.join(root, 'luci-app-mango-ikev2/root/usr/share/rpcd/acl.d/luci-app-mango-ikev2.json');
const viewPath = path.join(root, 'luci-app-mango-ikev2/htdocs/luci-static/resources/view/mango-ikev2/log.js');
const acl = JSON.parse(fs.readFileSync(aclPath, 'utf8'))['luci-app-mango-ikev2'];
const viewSource = fs.readFileSync(viewPath, 'utf8');

function fnmatch(pattern, text) {
	const result = spawnSync('python3', ['-c', `
import ctypes, sys
libc = ctypes.CDLL(None)
libc.fnmatch.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
libc.fnmatch.restype = ctypes.c_int
FNM_NOESCAPE = 2
raise SystemExit(0 if libc.fnmatch(sys.argv[1].encode(), sys.argv[2].encode(), FNM_NOESCAPE) == 0 else 1)
`, pattern, text], { encoding: 'utf8' });
	assert.equal(result.error, undefined);
	assert.ok(result.status === 0 || result.status === 1, result.stderr);
	return result.status === 0;
}

function loadEventsView() {
	assert.equal(viewSource.trim().endsWith('});'), true);
	const source = viewSource.replace('return view.extend({', 'var spec = {').replace(/\}\);\s*$/, '}; spec;');
	function E(tag, props, children) {
		return { tag, props: props || {}, children: children || [] };
	}
	return vm.runInNewContext(source, { E, String, parseInt, Math });
}

function labels(node, found) {
	found = found || [];
	if (!node || typeof node !== 'object')
		return found;
	if (node.tag === 'span' && node.props.class && node.props.class.indexOf('label') !== -1)
		found.push(String(node.children[0]));
	node.children.forEach(function(child) { labels(child, found); });
	return found;
}

function texts(node, found) {
	found = found || [];
	if (typeof node === 'string') {
		found.push(node);
		return found;
	}
	if (!node || typeof node !== 'object')
		return found;
	node.children.forEach(function(child) { texts(child, found); });
	return found;
}

test('event log grants are the two exact read paths', function() {
	const read = acl.read.file;
	const write = acl.write.file;
	assert.deepStrictEqual(read[VAR_LOG], ['read']);
	assert.deepStrictEqual(read[TMP_LOG], ['read']);
	assert.equal(write[VAR_LOG], undefined);
	assert.equal(write[TMP_LOG], undefined);
	for (const key of Object.keys(read)) {
		assert.equal(key.includes('*'), false, key);
		assert.equal(key.endsWith('/'), false, key);
		if (key.includes('mango-ikev2-events'))
			assert.ok(key === VAR_LOG || key === TMP_LOG, key);
	}
	for (const key of Object.keys(write)) {
		assert.equal(key.includes('mango-ikev2-events'), false, key);
		assert.equal(key.includes('*'), false, key);
	}
	assert.deepStrictEqual(acl.read.ubus.file, ['read', 'exec', 'stat']);
	assert.deepStrictEqual(acl.write.ubus.file, ['exec', 'write']);
});

test('rpcd fnmatch authorizes each real path and no wider name', function() {
	assert.equal(fnmatch(VAR_LOG, VAR_LOG), true);
	assert.equal(fnmatch(TMP_LOG, TMP_LOG), true);
	assert.equal(fnmatch(VAR_LOG, TMP_LOG), false);
	assert.equal(fnmatch(TMP_LOG, VAR_LOG), false);
	for (const grant of [VAR_LOG, TMP_LOG]) {
		assert.equal(fnmatch(grant, '/tmp/log/mango-ikev2-events.log.bak'), false);
		assert.equal(fnmatch(grant, '/tmp/log/'), false);
		assert.equal(fnmatch(grant, '/var/log/'), false);
		assert.equal(fnmatch(grant, '/tmp/log/other.log'), false);
	}
});

test('log page reads the var path and renders both ok and fail events', function() {
	const reads = viewSource.match(/fs\.read\('\/var\/log\/mango-ikev2-events\.log'\)/g) || [];
	assert.equal(reads.length, 2);
	assert.equal(viewSource.includes("fs.read('/tmp/log/mango-ikev2-events.log')"), false);
	assert.equal(viewSource.includes('暂无连接事件'), true);
	assert.equal(viewSource.includes('不含 strongSwan 明细'), true);
	const spec = loadEventsView();
	const empty = spec.renderEvents('');
	assert.equal(texts(empty).includes('暂无连接事件'), true);
	assert.deepStrictEqual(labels(empty), []);
	const sample = [
		'2026-11-09 17:20:01\tok\t主服务器\texample\tid\tconnected vip=10.0.0.1',
		'2026-11-09 17:21:01\tfail\t主服务器\texample\tid\tdatapath dead; redial',
		'2026-11-09 17:22:01\tfail\t主服务器\texample\tid\tredial',
		'2026-11-09 17:23:01\tfail\t主服务器\texample\tid\tdial failed (#1)',
		'2026-11-09 17:25:01\tok\t主服务器\texample\tid\tconnected vip=10.0.0.1'
	].join('\n');
	const shown = labels(spec.renderEvents(sample));
	assert.deepStrictEqual(shown, ['成功', '失败', '失败', '失败', '成功']);
	const many = Array.from({ length: 25 }, function(_, i) {
		return '2026-11-09 18:' + String(i).padStart(2, '0') + ':00\tok\t主服务器\texample\tid\tconnected';
	}).join('\n');
	assert.equal(labels(spec.renderEvents(many)).length, 20);
	assert.equal(labels(spec.renderEvents(many))[0], '成功');
});
