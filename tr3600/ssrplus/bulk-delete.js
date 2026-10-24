(function(exporter) {
    'use strict';
    if (typeof module === 'object' && module.exports) module.exports = exporter;
    else window.ssrBulkDelete = exporter;
})(function(root, options) {
    'use strict';
    if (!root || root.getAttribute('data-bulk-ready') === '1') return;
    root.setAttribute('data-bulk-ready', '1');
    var all = root.querySelector('.ssr-bulk-all');
    var button = root.querySelector('.ssr-bulk-delete');
    var count = root.querySelector('.ssr-bulk-count');
    var message = root.querySelector('.ssr-bulk-message');
    var busy = false;
    var form = root.closest('form');
    var edited = false;
    function markEdited(event) {
        if (event.target && /^cbid\./.test(event.target.name || '')) edited = true;
    }
    if (form) {
        form.addEventListener('input', markEdited);
        form.addEventListener('change', markEdited);
    }
    function boxes() { return Array.prototype.slice.call(root.querySelectorAll('.ssr-bulk-node')); }
    function selectable() { return boxes().filter(function(box) { return box.getAttribute('data-protected') !== '1'; }); }
    function selected() { return selectable().filter(function(box) { return box.checked; }); }
    function update() {
        var available = selectable(), n = selected().length;
        all.checked = available.length > 0 && n === available.length;
        all.indeterminate = n > 0 && n < available.length;
        all.disabled = busy || !available.length;
        button.disabled = busy || n === 0;
        count.textContent = options.selected.replace('%d', n);
        boxes().forEach(function(box) { box.disabled = busy || box.getAttribute('data-protected') === '1'; });
    }
    all.addEventListener('change', function() {
        if (busy) return;
        selectable().forEach(function(box) { box.checked = all.checked; });
        update();
    });
    boxes().forEach(function(box) {
        box.addEventListener('change', update);
        box.addEventListener('mousedown', function(event) { event.stopPropagation(); });
        box.addEventListener('dragstart', function(event) { event.preventDefault(); event.stopPropagation(); });
    });
    button.addEventListener('click', function() {
        if (busy) return;
        var ids = selected().map(function(box) { return box.value; });
        if (edited) { message.textContent = options.errors.pending_changes; return; }
        if (!ids.length || !options.confirm(options.question.replace('%d', ids.length))) return;
        var token = form && form.querySelector('input[name="token"]');
        if (!token || !token.value) { message.textContent = options.failed; return; }
        busy = true; message.textContent = ''; update();
        options.post(options.url, {ids: JSON.stringify(ids), token: token.value}, function(xhr, result) {
            if (xhr && xhr.status >= 200 && xhr.status < 300 && result && result.ret === 1) {
                options.reload(); return;
            }
            busy = false;
            message.textContent = result && options.errors[result.error] || options.failed;
            update();
        });
    });
    update();
});
