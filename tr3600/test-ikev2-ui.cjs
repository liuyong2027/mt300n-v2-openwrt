const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(
	__dirname, 'luci-app-mango-ikev2/htdocs/luci-static/resources/view/mango-ikev2.js'), 'utf8');

async function main() {
	assert.equal(source.includes('ui.changes.apply'), false);
	const calls = [];
	const messages = [];
	let enabled = '0';
	let changes = {mango_ikev2: [['set', 'main', 'enabled', '1']]};
	let reloadEnabled = null;
	const context = {
		view: {
			extend(page) {
				page.handleSave = function() {
					calls.push('save');
					return Promise.resolve();
				};
				return page;
			}
		},
		form: {},
		uci: {
			changes() { return Promise.resolve(changes); },
			callApply(timeout, rollback) {
				calls.push('apply:' + timeout + ':' + rollback);
				enabled = '1';
				return Promise.resolve(0);
			},
			callConfirm() {
				calls.push('confirm');
				return Promise.resolve(0);
			}
		},
		fs: {
			exec(file, args) {
				calls.push('reload:' + file + ':' + args.join(','));
				reloadEnabled = enabled;
				return Promise.resolve({code: 0, stdout: '', stderr: ''});
			}
		},
		ui: {
			addNotification(target, node, type) { messages.push({node, type}); }
		},
		E: (tag, attrs, text) => ({tag, attrs, text}),
		Promise,
		Object,
		Array
	};
	const page = vm.runInNewContext('(function(){\n' + source + '\n})()', context);

	await page.handleSaveApply();
	assert.equal(reloadEnabled, '1');
	assert.deepEqual(calls, ['save', 'apply:10:true', 'confirm', 'reload:/etc/init.d/mango_ikev2:reload']);
	assert.ok(calls.indexOf('confirm') < calls.indexOf('reload:/etc/init.d/mango_ikev2:reload'));
	assert.equal(messages.length, 0);

	enabled = '1';
	changes = {};
	calls.length = 0;
	reloadEnabled = null;
	await page.handleSaveApply();
	assert.equal(reloadEnabled, '1');
	assert.deepEqual(calls, ['save', 'reload:/etc/init.d/mango_ikev2:reload']);

	changes = {mango_ikev2: []};
	calls.length = 0;
	reloadEnabled = null;
	await page.handleSaveApply();
	assert.equal(reloadEnabled, '1');
	assert.deepEqual(calls, ['save', 'reload:/etc/init.d/mango_ikev2:reload']);

	page.handleSave = function() {
		calls.push('save');
		return Promise.reject(new Error('save failed'));
	};
	calls.length = 0;
	await page.handleSaveApply();
	assert.deepEqual(calls, ['save']);
	assert.equal(messages.at(-1).type, 'error');
	assert.match(messages.at(-1).node.text, /save failed/);

	console.log('IKEv2 LuCI: commit enabled=1 before reload; no-diff Save & Apply still reloads');
}

main().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
