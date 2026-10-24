"""Add current-page selection and one authenticated node-only deletion request."""
from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
MESSAGES = {
    'Select nodes': '选择节点',
    'Select all on this page': '全选当前页',
    'Delete selected nodes': '删除所选节点',
    'Selected %d nodes': '已选择 %d 个节点',
    'Delete %d selected nodes?': '确定删除选中的 %d 个节点吗？',
    'A configured service uses this node. Switch it before deleting.': '已有服务选用了此节点，请先切换节点再删除。',
    'Some selected nodes are in use. Switch them or uncheck them first.': '所选节点中有服务正在选用的节点，请先切换或取消勾选。',
    'Apply or discard pending SSR changes before deleting nodes.': '请先应用或撤销尚未应用的 SSR 修改，再删除节点。',
    'The node list changed. Reload the page and select again.': '节点列表已变化，请刷新页面后重新选择。',
    'Deletion failed. Reload the page and try again.': '删除失败，请刷新页面后重试。',
}

def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Pinned bulk-delete source changed: ' + repr(old[:90]))
    return text.replace(old, new, 1)

def patch(root):
    package = root / 'feeds/helloworld/luci-app-ssr-plus'
    changed = {}
    path = package / 'luasrc/controller/shadowsocksr.lua'
    text = path.read_text(encoding='utf-8')
    route = '\tentry({"admin", "services", "shadowsocksr", "delete_node"}, call("act_delete_node")).leaf = true'
    text = once(text, route, route + '\n\tentry({"admin", "services", "shadowsocksr", "delete_nodes"}, post("act_delete_nodes")).leaf = true')
    text = once(text, 'function add_subscribe_item()', (HERE / 'bulk-delete-controller.lua').read_text(encoding='utf-8') + '\nfunction add_subscribe_item()')
    changed[path] = text
    path = package / 'luasrc/model/cbi/shadowsocksr/servers.lua'
    text = path.read_text(encoding='utf-8')
    anchor = 's.server_base_url = luci.dispatcher.build_url("admin", "services", "shadowsocksr", "servers")'
    changed[path] = once(text, anchor, anchor + "\ns.server_bulk_protected = dofile('/usr/share/shadowsocksr/bulk_delete.lua').protected(uci)")
    path = package / 'luasrc/view/shadowsocksr/server_table.htm'
    text = path.read_text(encoding='utf-8')
    title = '\t%><tr class="tr cbi-section-table-titles <%=anonclass%>"<%=titlename%>><%\n'
    text = once(text, title, title + '\t%><th class="th cbi-section-table-cell ssr-bulk-selection"><%:Select nodes%></th><%\n')
    desc = '\t%><tr class="tr cbi-section-table-descr <%=anonclass%>"><%\n'
    text = once(text, desc, desc + '\t%><th class="th cbi-section-table-cell ssr-bulk-selection"></th><%\n')
    row = '\t\t<tr class="tr cbi-section-table-row<%=colorclass%>" id="cbi-<%=self.config%>-<%=section%>"<%=sectiontitle%>>\n'
    text = once(text, row, row + '''			<td class="td cbi-section-table-cell ssr-bulk-selection" data-title="<%:Select nodes%>">
				<input type="checkbox" class="ssr-bulk-node" value="<%=pcdata(section)%>" aria-label="<%:Select nodes%>"
					data-protected="<%=self.server_bulk_protected[section] and '1' or '0'%>"
					<%=ifattr(self.server_bulk_protected[section], 'disabled', 'disabled')%>
					<%=ifattr(self.server_bulk_protected[section], 'title', translate('A configured service uses this node. Switch it before deleting.'))%> />
			</td>
''')
    table = '\t<table class="table cbi-section-table ssr-numbered-server-table"'
    text = once(text, table, '''	<div class="ssr-bulk-controls" style="display:flex;flex-wrap:wrap;gap:.75em;align-items:center;margin:.5em 0">
		<label><input type="checkbox" class="ssr-bulk-all" /> <%:Select all on this page%></label>
		<button type="button" class="btn cbi-button cbi-button-remove ssr-bulk-delete" disabled="disabled"><%:Delete selected nodes%></button>
		<span class="ssr-bulk-count" aria-live="polite"></span>
		<span class="ssr-bulk-message" role="alert"></span>
	</div>
''' + table)
    def js(message):
        return '<%=luci.util.serialize_json(translate(' + json.dumps(message) + '))%>'
    script = '\n<script type="text/javascript">\n' + (HERE / 'bulk-delete.js').read_text(encoding='utf-8')
    script += '''
window.ssrBulkDelete(document.getElementById('cbi-shadowsocksr-servers'), {
    url: '<%=luci.dispatcher.build_url("admin", "services", "shadowsocksr", "delete_nodes")%>',
    confirm: function(message) { return window.confirm(message); },
    post: function(url, data, callback) { window.ssrXHR.post(url, data, callback); },
    reload: function() { window.location.reload(); },
'''
    script += '    selected: ' + js('Selected %d nodes') + ',\n'
    script += '    question: ' + js('Delete %d selected nodes?') + ',\n'
    script += '    failed: ' + js('Deletion failed. Reload the page and try again.') + ',\n'
    script += '    errors: {\n'
    for code, label in [('node_in_use', 'Some selected nodes are in use. Switch them or uncheck them first.'),
                        ('pending_changes', 'Apply or discard pending SSR changes before deleting nodes.'),
                        ('stale_selection', 'The node list changed. Reload the page and select again.')]:
        script += '        ' + code + ': ' + js(label) + ',\n'
    script += '    }\n});\n</script>\n'
    changed[path] = once(text, '<!-- /tblsection -->', '<!-- /tblsection -->' + script)
    path = package / 'po/zh_Hans/ssr-plus.po'
    text = path.read_text(encoding='utf-8')
    for message, translated in MESSAGES.items():
        if '\nmsgid ' + json.dumps(message) + '\n' in text:
            raise ValueError('Bulk-delete translation already exists: ' + message)
        text += '\nmsgid ' + json.dumps(message) + '\nmsgstr ' + json.dumps(translated, ensure_ascii=False) + '\n'
    changed[path] = text
    helper = (HERE / 'bulk_delete.lua').read_bytes()
    # Every pinned anchor is checked before any prepared file is modified.
    for path, text in changed.items():
        path.write_text(text, encoding='utf-8', newline='\n')
    (package / 'root/usr/share/shadowsocksr/bulk_delete.lua').write_bytes(helper)

if __name__ == '__main__':
    patch(Path(sys.argv[1]))
