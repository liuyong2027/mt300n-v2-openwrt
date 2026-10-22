#!/usr/bin/env python3
"""Keep node-list probes from flooding DNS or deleting an existing bypass."""
from pathlib import Path
import sys

root = Path(sys.argv[1]) / 'package/luci-app-ssr-plus/luasrc'
controller = root / 'controller/shadowsocksr.lua'
view = root / 'view/shadowsocksr/server_list.htm'
text = controller.read_text(encoding='utf-8')
before = '''	if domain then
		if use_nft then
			iret = luci.sys.call("nft add element inet ss_spec ss_spec_wan_ac { " .. domain .. " } 2>/dev/null") == 0
		else
			iret = luci.sys.call("ipset add ss_spec_wan_ac " .. domain .. " 2>/dev/null") == 0
		end
	end'''
after = '''	-- nft resolves hostnames itself; avoid extra DNS and never remove a pre-existing bypass.
	if is_ip and require("luci.cbi.datatypes").ip4addr(domain) then
		if use_nft then
			local present = luci.sys.call("nft get element inet ss_spec ss_spec_wan_ac { " .. domain .. " } >/dev/null 2>&1") == 0
			if not present then
				iret = luci.sys.call("nft add element inet ss_spec ss_spec_wan_ac { " .. domain .. " } 2>/dev/null") == 0
			end
		else
			local present = luci.sys.call("ipset test ss_spec_wan_ac " .. domain .. " >/dev/null 2>&1") == 0
			if not present then
				iret = luci.sys.call("ipset add ss_spec_wan_ac " .. domain .. " 2>/dev/null") == 0
			end
		end
	end'''
assert text.count(before) == 1
controller.write_text(text.replace(before, after), encoding='utf-8', newline='\n')
text = view.read_text(encoding='utf-8')
before = 'for (let i = 0; i < 20; i++) worker();'
assert text.count(before) == 1
view.write_text(text.replace(before, '// One probe at a time on the 128 MiB MT7628.\n\t\tworker();'), encoding='utf-8', newline='\n')
print('Node probes serialized; domain probes leave the firewall untouched; existing IP bypasses retained')
