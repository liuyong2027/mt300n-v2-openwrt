#!/usr/bin/env python3
"""Integrate the validated node-only YAML importer and subscription UI defaults."""
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
OLD_FILTER_WORDS = '过期/重置/套餐/剩余/网址/QQ群/官网/防失联/回国'
FILTER_WORDS = OLD_FILTER_WORDS + '/邮箱客服/支持AI'


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Pinned SSR subscription source changed: {old[:100]!r}')
    return text.replace(old, new, 1)


def yaml_importer(text):
    text = once(text, '\t\tlocal backend_refresh = group_needs_ss_backend_refresh(groupHash)', '''		-- cudy YAML node-only import v1; all parsing precedes any UCI diff.
		local yaml_nodes
		if not should_use_mihomo_mode() and isClashYAML(raw) then
			local ok, parsed = pcall(function()
				local helper = dofile("/usr/share/shadowsocksr/yaml_nodes.lua")
				local result = helper.parse(raw, function(provider_url, provider_ua)
					return curl(provider_url, provider_ua or user_agent)
				end)
				local yaml_digest = "yaml-nodes-v1"
				for _, node in ipairs(result) do
					node.yaml_node_import = "1"
					local signature = helper.signature(node)
					node.hashkey = md5(signature)
					yaml_digest = md5(yaml_digest .. node.hashkey)
				end
				new_md5 = yaml_digest
				return result
			end)
			if ok then
				yaml_nodes = parsed
			else
				-- Never log subscription bodies, credentials, or parser exceptions.
				local code = tostring(parsed):match("yaml_nodes:([%w_:%-?]+)") or "parse_or_conversion_failed"
				log("YAML node import failed; keeping old nodes: " .. code)
				raw = ""
			end
		end
		local backend_refresh = group_needs_ss_backend_refresh(groupHash)''')
    text = once(text, '\t\t\tif isClashYAML(raw) then\n\t\t\t\tis_clash_subscription = true', '''			if yaml_nodes then
				nodes = yaml_nodes
				szType = "yaml_nodes"
			elseif isClashYAML(raw) then
				is_clash_subscription = true''')
    return once(text,
        '(result.type ~= "clash" and result.server:match("[^0-9a-zA-Z%-_%.%s]"))',
        '(result.type ~= "clash" and not yaml_nodes and result.server:match("[^0-9a-zA-Z%-_%.%s]"))')


def align_server_table(text):
    # Template children emit supporting markup, not a data cell. Only actual
    # CBI options may contribute a title or description column.
    for name in ('render_titles', 'render_descriptions'):
        start = text.index('function ' + name + '()')
        end = text.index('\nend', start) + len('\nend')
        block = text[start:end]
        fixed = once(block, 'if not k.optional then', 'if not k.optional and k.option then')
        text = text[:start] + fixed + text[end:]
    return text


def patch(root):
    package = root / 'feeds/helloworld/luci-app-ssr-plus'
    changed = {}
    for relative in (
        'luasrc/model/cbi/shadowsocksr/servers.lua',
        'root/usr/share/shadowsocksr/subscribe.lua',
        'root/usr/share/shadowsocksr/shadowsocksr.config',
        'root/etc/init.d/shadowsocksr',
    ):
        path = package / relative
        changed[path] = once(path.read_text(encoding='utf-8'), OLD_FILTER_WORDS, FILTER_WORDS)
    ui = package / 'luasrc/model/cbi/shadowsocksr/servers.lua'
    changed[ui] = once(changed[ui], 'o:value("v2rayN/9.99", "v2rayN")',
        'o:value("v2rayN/9.99", "v2rayN")\no:value("mihomo/1.18.0", "Mihomo (mihomo/1.18.0)")')
    table = package / 'luasrc/view/shadowsocksr/server_table.htm'
    text = align_server_table(table.read_text(encoding='utf-8'))
    # Both header renderers have the same child loop; patch their distinct prefixes.
    title = '\t%><tr class="tr cbi-section-table-titles <%=anonclass%>"<%=titlename%>><%\n'
    text = once(text, title, title + '\t%><th class="th cbi-section-table-cell ssr-node-number-header"><%:No.%></th><%\n')
    description = '\t%><tr class="tr cbi-section-table-descr <%=anonclass%>"><%\n'
    text = once(text, description, description + '\t%><th class="th cbi-section-table-cell ssr-node-number-header"></th><%\n')
    text = once(text, '\t<table class="table cbi-section-table">',
        '\t<table class="table cbi-section-table ssr-numbered-server-table" style="counter-reset: ssr-node-number <%=math.max(first_index - 1, 0)%>;">')
    row = '\t\t<tr class="tr cbi-section-table-row<%=colorclass%>" id="cbi-<%=self.config%>-<%=section%>"<%=sectiontitle%>>\n'
    text = once(text, row, row + '\t\t\t<td class="td cbi-section-table-cell ssr-node-number" data-title="<%:No.%>"></td>\n')
    text = once(text, '<style type="text/css">', '''<style type="text/css">
	.ssr-numbered-server-table .ssr-node-number,
	.ssr-numbered-server-table .ssr-node-number-header {
		width: 3.5em;
		text-align: center;
		white-space: nowrap;
		font-variant-numeric: tabular-nums;
	}
	.ssr-numbered-server-table .ssr-node-number {
		counter-increment: ssr-node-number;
	}
	.ssr-numbered-server-table .ssr-node-number::before {
		content: counter(ssr-node-number);
	}''')
    changed[table] = text
    translation = package / 'po/zh_Hans/ssr-plus.po'
    text = translation.read_text(encoding='utf-8')
    if 'msgid "No."' in text:
        raise ValueError('Pinned SSR translation already has a node number label')
    changed[translation] = text.rstrip() + '''

msgid "No."
msgstr "编号"

msgid "Access Scope controls who may connect."
msgstr "访问范围用于控制哪些设备可以连接此服务端。"

msgid "Traffic handling"
msgstr "流量处理说明"

msgid "Shadowsocks decrypted TCP and UDP follow the SSR Plus+ client policy and selected proxy ports."
msgstr "普通 SS 解密后的 TCP、UDP 按 SSR Plus+ 客户端分流规则及所选代理端口处理。"

msgid "This server's traffic follows the router's own outbound policy."
msgstr "此类服务端的流量按路由器自身出站策略处理。"
'''
    subscribe = package / 'root/usr/share/shadowsocksr/subscribe.lua'
    changed[subscribe] = yaml_importer(changed[subscribe])
    defaults = package / 'root/etc/uci-defaults/luci-ssr-plus'
    old = '''    if [ -z "$current_filter_words" ]; then
        uci -q set shadowsocksr.@server_subscribe[0].filter_words=''' + "'" + OLD_FILTER_WORDS + "'" + '''
    elif ! printf '%s\\n' "$current_filter_words" | grep -q '重置'; then
        uci -q set shadowsocksr.@server_subscribe[0].filter_words="${current_filter_words}/重置"
    fi'''
    new = '''    # Upgrade only the known old default; retain owner-supplied filters.
    if [ -z "$current_filter_words" ] || [ "$current_filter_words" = ''' + "'" + OLD_FILTER_WORDS + "'" + ''' ]; then
        uci -q set shadowsocksr.@server_subscribe[0].filter_words=''' + "'" + FILTER_WORDS + "'" + '''
    fi'''
    changed[defaults] = once(defaults.read_text(encoding='utf-8'), old, new)
    # Defaults only: keep-settings upgrades must not erase owner-maintained
    # lists. No runtime UCI migration or startup truncation is introduced.
    config = package / 'root/usr/share/shadowsocksr/shadowsocksr.config'
    changed[config], count = re.subn(r"(?m)^[ \t]*list[ \t]+wan_fw_ips[ \t]+[^\n]*\n", '', changed[config])
    if count != 7:
        raise ValueError('Pinned forced WAN IP defaults changed')
    for name in ('white.list', 'deny.list'):
        path = package / 'root/etc/ssrplus' / name
        if not path.is_file():
            raise ValueError('Missing pinned access list: ' + name)
        changed[path] = ''
    # Read every input and verify every pinned anchor before writing sources.
    helper = (HERE / 'yaml_nodes.lua').read_bytes()
    for path, text in changed.items():
        path.write_text(text, encoding='utf-8', newline='\n')
    (package / 'root/usr/share/shadowsocksr/yaml_nodes.lua').write_bytes(helper)


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
