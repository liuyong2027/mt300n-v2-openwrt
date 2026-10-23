const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function E(tag, attrs = {}, children = []) {
  attrs ||= {};
  const flat = (Array.isArray(children) ? children : [children]).filter(x => x != null);
  assert(!flat.some(Array.isArray), 'LuCI DOM children must be flat');
  const node = {
    // HTML boolean attributes are true whenever present, even checked="false".
    tag, attrs, children: flat, value: attrs.value || '', checked: attrs.checked != null, disabled: !!attrs.disabled,
    appendChild(x) { this.children.push(x); }, replaceChildren(...xs) { this.children = xs; }
  };
  if (tag === 'select') node.value = flat.find(x => x.tag === 'option')?.attrs.value || '';
  return node;
}
function nodes(x) { return typeof x === 'object' && x ? [x, ...(x.children || []).flatMap(nodes)] : []; }
function text(x) { return typeof x === 'string' ? x : String(x == null ? '' : (x.children || []).map(text).join('')); }
function button(x, label) { return nodes(x).find(n => n.tag === 'button' && text(n) === label); }
function fixture(overrides = {}) {
  let state = {
    enabled: true, port: 8388, method: 'aes-128-gcm', listen: '192.168.7.6', subnet: '192.168.7.0/24',
    network_name: '<img onerror=alert(1)>', network_online: true, ready: true, applying: false,
    error: '', password_set: true, ...overrides
  };
  let modal = null, nextFailure = null, configureResult = { applying: true, message: '正在应用' };
  const calls = [], notifications = [], pollCallbacks = new Set(), declarations = [];
  const rpc = { declare(spec) {
    declarations.push(spec);
    assert.equal(spec.object, 'cudy.ss');
    return async (...args) => {
      calls.push({ method: spec.method, args });
      if (nextFailure) { const failure = nextFailure; nextFailure = null; return failure; }
      if (spec.method === 'status') return { ok: true, result: { ...state } };
      if (spec.method === 'configure') {
        if (configureResult.applying) state.applying = true;
        return { ok: true, result: configureResult };
      }
      if (spec.method === 'client') return { ok: true, result: {
        server: '192.168.7.6', port: 8388, method: 'aes-128-gcm',
        password: 'only-on-explicit-client-click', uri: 'ss://secret@192.168.7.6:8388#<script>'
      } };
      throw new Error('unexpected method');
    };
  } };
  const ui = {
    showModal(title, content) { modal = E('div', {}, [E('h3', {}, title)].concat(content)); },
    hideModal() { modal = null; },
    addNotification(_, node, kind) { notifications.push({ message: text(node), kind }); }
  };
  const poll = { add(fn, interval) { assert.equal(interval, 2); pollCallbacks.add(fn); }, remove(fn) { pollCallbacks.delete(fn); } };
  const source = fs.readFileSync(process.argv[2] || path.join(__dirname, 'luci-app-cudy-ss/htdocs/luci-static/resources/view/cudy-ss.js'), 'utf8');
  const view = vm.runInNewContext('(function(){' + source + '})()', { view: { extend: x => x }, rpc, ui, poll, E, Promise, Error, Number, String });
  return { view, calls, notifications, declarations, pollCallbacks,
    get state() { return state; }, set state(value) { state = value; },
    get modal() { return modal; },
    fail(value) { nextFailure = value; },
    async tick() { await Promise.all(Array.from(pollCallbacks).map(fn => fn())); }
  };
}

(async function() {
  const f = fixture();
  const root = f.view.render(await f.view.load());
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].method, 'status');
  assert(text(root).includes('服务运行中'));
  assert(f.view.controls.enabled.checked, 'enabled service renders checked');
  assert(text(root).includes('192.168.7.0/24'));
  assert(text(root).includes('<img onerror=alert(1)>'));
  assert(!nodes(root).some(x => x.tag === 'img'), 'backend labels render as text');
  assert.equal(f.view.controls.password.value, '', 'status does not populate password');
  assert.equal(f.declarations.find(x => x.method === 'configure').params.join(','), 'enabled,port,method,password');
  assert(!nodes(root).some(x => x.tag === 'option' && x.attrs.value === 'none'));
  assert(!nodes(root).some(x => ['192.168.7.6', '192.168.7.0/24'].includes(x.value)), 'scope cannot be edited');

  f.view.controls.port.value = '8389';
  f.view.controls.method.value = 'aes-256-gcm';
  await button(root, '保存并应用').attrs.click();
  const configure = f.calls.find(x => x.method === 'configure');
  assert.deepEqual(configure.args, [true, 8389, 'aes-256-gcm', '']);
  assert(f.view.busy && f.view.controls.apply.disabled && f.view.controls.client.disabled);
  assert(text(root).includes('正在应用'));
  assert.equal(f.pollCallbacks.size, 1);
  await button(root, '保存并应用').attrs.click();
  assert.equal(f.calls.filter(x => x.method === 'configure').length, 1, 'applying rejects duplicate submit');
  await f.tick();
  assert.equal(f.pollCallbacks.size, 1, 'pending polls do not register duplicate callbacks');
  assert.equal(f.calls.filter(x => x.method === 'client').length, 0, 'background polling never fetches secrets');
  f.state = { ...f.state, applying: false, port: 8389, method: 'aes-256-gcm', ready: true };
  await f.tick();
  assert.equal(f.pollCallbacks.size, 0);
  assert.equal(f.view.controls.port.value, '8389');
  assert.equal(f.view.controls.method.value, 'aes-256-gcm');
  assert(!f.view.controls.apply.disabled);
  assert.equal(f.notifications.at(-1).message, '设置已应用。');

  await button(root, '查看客户端配置').attrs.click();
  assert.equal(f.calls.filter(x => x.method === 'client').length, 1);
  assert(f.modal);
  assert(nodes(f.modal).some(x => x.tag === 'input' && x.attrs.readonly && x.value === 'only-on-explicit-client-click'));
  assert(text(f.modal).includes('ss://secret@192.168.7.6:8388#<script>'));
  assert(!nodes(f.modal).some(x => x.tag === 'script'), 'client URI is safe text');
  button(f.modal, '关闭').attrs.click();
  assert.equal(f.modal, null);
  assert(!text(root).includes('only-on-explicit-client-click'), 'secret is confined to explicit modal');

  f.view.controls.password.value = 'tiny';
  await f.view.applySettings();
  assert.equal(f.calls.filter(x => x.method === 'configure').length, 1);
  assert(f.notifications.at(-1).message.includes('24–128'));
  f.view.controls.password.value = '';
  for (const invalid of ['1023', '65536', '2e4', '12345', '10808', '0', '-1', '8388.5']) {
    f.view.controls.port.value = invalid;
    await f.view.applySettings();
    assert.equal(f.calls.filter(x => x.method === 'configure').length, 1, 'invalid port rejected: ' + invalid);
  }
  f.view.controls.port.value = '8388';
  f.view.controls.method.value = 'none';
  await f.view.applySettings();
  assert.equal(f.calls.filter(x => x.method === 'configure').length, 1);
  f.view.controls.method.value = 'chacha20-ietf-poly1305';
  f.view.controls.password.value = 'X'.repeat(24);
  f.fail({ ok: false, message: '共享端口已被占用' });
  await f.view.applySettings();
  assert.equal(f.notifications.at(-1).message, '共享端口已被占用');
  assert(!f.view.controls.apply.disabled, 'failed submit releases UI');
  assert.equal(f.view.controls.password.value, 'X'.repeat(24), 'failed submit permits correction without refilling password');

  for (const invalid of ['X'.repeat(24) + '\n', 'X'.repeat(24) + '\x7f', 'X'.repeat(24) + '\ud800', '\udc00' + 'X'.repeat(24), '中'.repeat(43), '🔑'.repeat(33)]) {
    f.view.controls.password.value = invalid;
    const before = f.calls.filter(x => x.method === 'configure').length;
    await f.view.applySettings();
    assert.equal(f.calls.filter(x => x.method === 'configure').length, before, 'control/invalid UTF-16/overlong UTF-8 key rejected');
  }
  for (const password of ['中'.repeat(8), '🔑'.repeat(6)]) {
    f.view.controls.password.value = password;
    f.fail({ ok: false, message: 'accepted-by-client-validation' });
    await f.view.applySettings();
    assert.equal(f.calls.at(-1).method, 'configure');
    assert.equal(f.calls.at(-1).args[3], password, 'valid 24-byte UTF-8 key passes unchanged');
  }

  f.fail({ ok: false, message: '状态服务暂时不可用' });
  await button(root, '刷新状态').attrs.click();
  assert.equal(f.notifications.at(-1).message, '状态服务暂时不可用');
  assert(text(root).includes('状态读取失败'));
  await button(root, '刷新状态').attrs.click();
  assert(text(root).includes('服务运行中'));
  f.fail({ ok: false, message: '没有权限读取客户端配置' });
  await button(root, '查看客户端配置').attrs.click();
  assert.equal(f.notifications.at(-1).message, '没有权限读取客户端配置');
  assert(!f.modal && !f.view.controls.client.disabled);

  const fresh = fixture({ enabled: false, password_set: false, ready: false });
  const freshRoot = fresh.view.render(await fresh.view.load());
  assert(text(freshRoot).includes('服务已关闭'));
  assert.equal(fresh.view.controls.enabled.checked, false, 'disabled service must render unchecked with real HTML boolean-attribute semantics');
  assert(fresh.view.controls.client.disabled);
  fresh.view.controls.enabled.checked = true;
  await fresh.view.applySettings();
  assert.equal(fresh.calls.length, 1, 'first enable requires password');
  fresh.view.controls.password.value = 'Y'.repeat(129);
  await fresh.view.applySettings();
  assert.equal(fresh.calls.length, 1);
  fresh.view.controls.password.value = 'Y'.repeat(128);
  await fresh.view.applySettings();
  assert.equal(fresh.calls.filter(x => x.method === 'configure').length, 1);
  assert.equal(fresh.calls.find(x => x.method === 'configure').args[3].length, 128);
  fresh.state = { ...fresh.state, applying: false, error: '启动失败，已恢复原设置', enabled: false };
  await fresh.tick();
  assert(text(freshRoot).includes('启动失败，已恢复原设置'));
  assert.equal(fresh.pollCallbacks.size, 0);

  const pending = fixture({ applying: true });
  pending.view.render(await pending.view.load());
  assert.equal(pending.pollCallbacks.size, 1, 'reopening during application resumes status polling');
  pending.fail({ ok: false, message: '短暂断开' });
  await pending.tick();
  assert(pending.view.busy && pending.pollCallbacks.size === 1, 'temporary status failure keeps pending operation locked');
  pending.state = { ...pending.state, applying: false };
  await pending.tick();
  assert(!pending.view.busy && pending.pollCallbacks.size === 0);

  const offline = fixture({ network_online: false, ready: false });
  assert(text(offline.view.render(await offline.view.load())).includes('等待 ZeroTier 网络上线'));

  const menu = JSON.parse(fs.readFileSync(path.join(__dirname, 'luci-app-cudy-ss/root/usr/share/luci/menu.d/luci-app-cudy-ss.json')));
  assert.equal(menu['admin/services/cudy_ss'].title, 'SS 服务端');
  assert.equal(menu['admin/services/cudy_ss'].action.path, 'cudy-ss');
  const acl = JSON.parse(fs.readFileSync(path.join(__dirname, 'luci-app-cudy-ss/root/usr/share/rpcd/acl.d/luci-app-cudy-ss.json')));
  assert.deepEqual(acl['luci-app-cudy-ss'].read, { ubus: { 'cudy.ss': ['status'] } });
  assert.deepEqual(acl['luci-app-cudy-ss'].write, { ubus: { 'cudy.ss': ['configure', 'client'] } });
  console.log('PASS SS LuCI RPC contract, flat DOM, apply queue/polling, validation, error recovery, explicit secret reveal, narrow ACL');
})().catch(error => { console.error(error); process.exitCode = 1; });
