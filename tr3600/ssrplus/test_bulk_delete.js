'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const mount = require('./bulk-delete.js');
function element(value, protectedNode) {
    return {value: value || '', checked: false, disabled: false, textContent: '', attributes: {}, events: {},
        getAttribute(name) { return name === 'data-protected' ? (protectedNode ? '1' : '0') : this.attributes[name]; },
        setAttribute(name, v) { this.attributes[name] = v; },
        addEventListener(name, fn) { this.events[name] = fn; },
        fire(name) { if (this.events[name]) this.events[name]({stopPropagation() {}, preventDefault() {}}); }};
}
function setup() {
    const nodes = [element('b'), element('c'), element('a', true)];
    const all = element(), button = element(), count = element(), message = element();
    const token = {value: 'synthetic-csrf-token'};
    const state = {requests: [], confirmations: [], reloads: 0, confirm: true};
    const fields = {'.ssr-bulk-all': all, '.ssr-bulk-delete': button, '.ssr-bulk-count': count, '.ssr-bulk-message': message};
    const root = element(); root.querySelector = selector => fields[selector];
    root.querySelectorAll = selector => { assert.equal(selector, '.ssr-bulk-node'); return nodes; };
    const form = element(); form.querySelector = () => token;
    root.closest = () => form;
    mount(root, {selected: 'Selected %d nodes', question: 'Delete %d?', failed: 'Failed',
        errors: {node_in_use: 'In use', pending_changes: 'Save edits first'}, url: '/delete_nodes',
        confirm: question => { state.confirmations.push(question); return state.confirm; },
        post: (url, data, callback) => state.requests.push({url, data, callback}), reload: () => state.reloads++});
    return {nodes, all, button, count, message, token, state, form};
}
test('page selection skips protected nodes and supports clearing', () => {
    const x = setup(); assert.equal(x.button.disabled, true);
    x.all.checked = true; x.all.fire('change');
    assert.deepEqual(x.nodes.map(n => n.checked), [true, true, false]);
    assert.equal(x.count.textContent, 'Selected 2 nodes');
    x.all.checked = false; x.all.fire('change'); assert.equal(x.button.disabled, true);
});
test('individual selection updates partial selection and count', () => {
    const x = setup(); x.nodes[1].checked = true; x.nodes[1].fire('change');
    assert.equal(x.all.indeterminate, true); assert.equal(x.button.disabled, false);
    assert.equal(x.count.textContent, 'Selected 1 nodes');
});
test('cancel confirmation does not send a deletion request', () => {
    const x = setup(); x.nodes[0].checked = true; x.state.confirm = false; x.button.fire('click');
    assert.equal(x.state.requests.length, 0); assert.equal(x.nodes[0].checked, true);
});
test('one request contains only selected page nodes and CSRF token', () => {
    const x = setup(); x.all.checked = true; x.all.fire('change'); x.button.fire('click'); x.button.fire('click');
    assert.equal(x.state.requests.length, 1); const r = x.state.requests[0];
    assert.deepEqual(JSON.parse(r.data.ids), ['b', 'c']); assert.equal(r.data.token, x.token.value);
    assert.equal(x.state.confirmations[0], 'Delete 2?'); assert.equal(x.button.disabled, true);
    r.callback({status: 200}, {ret: 1, deleted: 2}); assert.equal(x.state.reloads, 1);
});
test('HTTP failure preserves selection and reports a specific error', () => {
    const x = setup(); x.nodes[0].checked = true; x.button.fire('click');
    x.state.requests[0].callback({status: 409}, {ret: 0, error: 'node_in_use'});
    assert.equal(x.message.textContent, 'In use'); assert.equal(x.nodes[0].checked, true);
    assert.equal(x.state.reloads, 0); assert.equal(x.button.disabled, false);
});
test('missing CSRF token and empty selections never send requests', () => {
    const x = setup(); x.button.fire('click'); assert.equal(x.state.requests.length, 0);
    x.nodes[0].checked = true; x.token.value = ''; x.button.fire('click');
    assert.equal(x.state.requests.length, 0); assert.equal(x.message.textContent, 'Failed');
});
test('unsaved form edits are not lost by deleting nodes and reloading', () => {
    const x = setup(); x.nodes[0].checked = true;
    x.form.events.input({target: {name: 'cbid.shadowsocksr.synthetic.alias'}});
    x.button.fire('click'); assert.equal(x.state.requests.length, 0);
    assert.equal(x.message.textContent, 'Save edits first'); assert.equal(x.state.reloads, 0);
});
