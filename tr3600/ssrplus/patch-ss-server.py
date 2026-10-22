#!/usr/bin/env python3
"""Patch the pinned SSR Plus+ server UI and host server lifecycle only."""
from pathlib import Path
import re
import sys

PROFILE = Path(__file__).resolve().parent

CHECK_STATUS = '''function check_status()
    local e = { ret = 1 }
    local probes = {
        google = { url = "https://www.google.com/generate_204", exact = "204" },
        baidu = { url = "https://www.baidu.com/" }
    }
    local probe = probes[luci.http.formvalue("set") or ""]
    if probe then
        -- URLs come only from this fixed allowlist. A failed transfer appends
        -- an error token so a partial response cannot be mistaken for success.
        local code = luci.sys.exec("curl -4 --connect-timeout 4 --max-time 8 -sS -o /dev/null -w '%{http_code}' '"
            .. probe.url .. "' 2>/dev/null || printf ' error'") or ""
        code = code:match("^%s*(%d%d%d)%s*$")
        if code and ((probe.exact and code == probe.exact) or
            (not probe.exact and code:match("^[23]%d%d$"))) then e.ret = 0 end
    end
    luci.http.prepare_content("application/json")
    luci.http.write_json(e)
end'''


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Pinned SSR server source changed: {old[:100]!r}')
    return text.replace(old, new, 1)


def patch(root):
    package = root / 'feeds/helloworld/luci-app-ssr-plus'
    config_path = package / 'luasrc/model/cbi/shadowsocksr/server-config.lua'
    config = config_path.read_text(encoding='utf-8')
    config, count = re.subn(r'local v_ss_encrypt_method_list = \{\n.*?\n\}',
        "local v_ss_encrypt_method_list = require('cudy.ssr-server').methods", config,
        count=1, flags=re.S)
    if count != 1:
        raise ValueError('Pinned Xray SS method list changed')
    config = once(config,
        'o:depends("type", "trojan")\no:depends("type", "shadowsocks")\no:depends("type", "ssr-xray")',
        'o:depends("type", "trojan")\no:depends("type", "ssr-xray")')
    config = once(config, 'o.default = "socks5"', '''o.default = "socks5"
function o.validate(self, value, section)
    local raw = self.map.uci:get_all('shadowsocksr', section) or {}
    raw['.name'] = section
    if require('cudy.ssr-server').private(raw) and value ~= 'shadowsocks' then
        return nil, translate('The reserved ZeroTier service must remain Shadowsocks')
    end
    return value
end''')
    config = once(config,
        'o = s:option(Value, "ss_password", translate("Shadowsocks Password"))\no.password = true\no.rmempty = true',
        'o = s:option(Value, "ss_password", translate("Shadowsocks Password"))\no.password = true\no.rmempty = false')
    config = once(config,
        'for _, v in ipairs(v_ss_encrypt_method_list) do o:value(v) end\no.default = "chacha20-ietf-poly1305"\no.rmempty = true',
        '''local cudy_ss_model = require('cudy.ssr-server')
local cudy_ss_raw = m.uci:get_all('shadowsocksr', sid) or {}
cudy_ss_raw['.name'] = sid
local cudy_ss_private = cudy_ss_model.private(cudy_ss_raw)
local cudy_visible = {}
for _, v in ipairs(v_ss_encrypt_method_list) do
    if not cudy_ss_private or v == 'aes-128-gcm' or v == 'aes-256-gcm' or v == 'chacha20-ietf-poly1305' then
        o:value(v); cudy_visible[v] = true
    end
end
if cudy_ss_raw.ss_method and not cudy_visible[cudy_ss_raw.ss_method] then
    o:value(cudy_ss_raw.ss_method, cudy_ss_raw.ss_method .. ' (' .. translate('existing value; verify support') .. ')')
end
o.default = "chacha20-ietf-poly1305"
o.rmempty = false
function o.validate(self, value, section)
    local password = luci.http.formvalue('cbid.shadowsocksr.' .. section .. '.ss_password')
        or self.map.uci:get('shadowsocksr', section, 'ss_password')
        or self.map.uci:get('shadowsocksr', section, 'password')
    if cudy_ss_private and value ~= 'aes-128-gcm' and value ~= 'aes-256-gcm' and value ~= 'chacha20-ietf-poly1305' then
        return nil, translate('The approved private service supports its original three AEAD methods')
    end
    -- The private page validates the complete submitted candidate using the
    -- namespace runtime's shared credential helper, including fresh/off rows.
    if cudy_ss_private then return value end
    local valid, result = pcall(cudy_ss_model.method, value, password)
    if not valid then return nil, tostring(result) end
    return value
end''')
    config = once(config, 'o.default = "tcp,udp"\no.rmempty = true\no:depends("type", "shadowsocks")',
        'o.default = "tcp,udp"\no.rmempty = false\no:depends("type", "shadowsocks")')
    begin = config.index('o = s:option(Flag, "bind_local",')
    end = config.index('o = s:option(ListValue, "naive_alpn",', begin)
    config = config[:begin] + (PROFILE / 'server-access-ui.lua').read_text(encoding='utf-8') + '\n' + config[end:]

    listing_path = package / 'luasrc/model/cbi/shadowsocksr/server.lua'
    listing = listing_path.read_text(encoding='utf-8')
    listing = once(listing,
        'local method = self.map:get(section, "encrypt_method") or self.map:get(section, "encrypt_method_ss")',
        'local method = self.map:get(section, "ss_method") or self.map:get(section, "encrypt_method") or self.map:get(section, "encrypt_method_ss")')
    listing = once(listing, '\nreturn m', '''
o = sec:option(DummyValue, "ss_network", translate("Server Transport"))
function o.cfgvalue(self, section)
    if self.map:get(section, "type") == "shadowsocks" then
        return self.map:get(section, "ss_network") or "tcp,udp"
    end
    return "-"
end
o = sec:option(DummyValue, "cudy_access", translate("Access Scope"))
function o.cfgvalue(self, section)
    local raw = self.map.uci:get_all('shadowsocksr', section) or {}
    raw['.name'] = section
    if require('cudy.ssr-server').private(raw) then return translate('Approved ZeroTier only') end
    return raw.cudy_access or (raw.bind_local == '1' and 'loopback' or (raw.accept_lan == '1' and 'lan' or 'loopback'))
end

return m''')

    status_path = package / 'luasrc/model/cbi/shadowsocksr/status.lua'
    status = status_path.read_text(encoding='utf-8')
    status = once(status, 'if Process_list:find("ssr.server") then',
        'if Process_list:find("ssr.server") or Process_list:find("/xray%-server%-%d+") then')
    status = once(status,
        'if Process_list:find("mihomo") and Process_list:find("/ss%-server%-") then\n\tserver_run = 1\nend',
        '''if Process_list:find("mihomo") and Process_list:find("/ss%-server%-") then
\tserver_run = 1
end
-- ready alone is also true for an intentionally stopped private service.
-- Check requested/global enable and actual availability before readiness.
local cudy_private_requested = false
uci:foreach('shadowsocksr', 'server_config', function(s)
    if s['.name'] == 'cudy_zt_private' and s.enable == '1' then cudy_private_requested = true end
end)
if cudy_private_requested and uci:get_first('shadowsocksr', 'server_global', 'enable_server', '0') == '1'
    and luci.sys.call('/usr/libexec/cudy-ss-zt available >/dev/null 2>&1 && /usr/libexec/cudy-ss-zt ready >/dev/null 2>&1') == 0 then
    server_run = 1
end''')

    init_path = package / 'root/etc/init.d/shadowsocksr'
    init = init_path.read_text(encoding='utf-8')
    begin = init.index('start_server() {\n')
    end = init.index('\nstart_switch() {', begin)
    server = init[begin:end]
    server = once(server, 'start_server() {\n', '''start_server() {
    [ "$USE_TABLES" = nftables ] || { echolog "Scoped servers require nftables/fw4"; return 1; }
    /usr/libexec/cudy-ssr-server-firewall prepare || return 1
''')
    server = once(server, '\tserver_service() {\n', '''\tserver_service() {
        # Never fall back to a host listener if any private identity field is lost.
        [ "$1" = cudy_zt_private ] && return 0
        [ "$(uci_get_by_name "$1" cudy_private 0)" = 1 ] && return 0
        [ "$(uci_get_by_name "$1" cudy_access '')" = zerotier ] && return 0
''')
    server = once(server,
        '\t\tserver_count=$((server_count + 1))',
        '\t\t/usr/libexec/cudy-ssr-server-rules validate "$1" || return 1\n\t\tserver_count=$((server_count + 1))')
    chain_begin = server.index('\t\tif [ "$server_count" = "1" ]; then\n')
    chain_end = server.index('\n\t\tlocal node_type', chain_begin)
    server = server[:chain_begin] + server[chain_end:]
    server = once(server, '\t\tvmess|vless|trojan|shadowsocks)', '''        shadowsocks)
            xray_bin="$(first_type xray)"
            [ -x "$xray_bin" ] || return 1
            config_file="$TMP_PATH/xray-server-$server_count.json"
            lua /usr/share/shadowsocksr/gen_cudy_ss_server.lua "$1" > "$config_file" || return 1
            "$xray_bin" run -test -c "$config_file" >> /var/ssrplus.log 2>&1 || return 1
            ln_start_bin "$xray_bin" xray-server-$server_count run -c "$config_file"
            echolog "Server: Xray Shadowsocks Server$server_count started with scoped access"
            ;;
\t\tvmess|vless|trojan)''')
    firewall_begin = server.index('\n\t\tserver_port=$(uci_get_by_name "$1" server_port)\n')
    firewall_end = server.index('\n\t\treturn 0\n', firewall_begin)
    server = server[:firewall_begin] + '\n\t\t/usr/libexec/cudy-ssr-server-firewall add "$1" || return 1\n' + server[firewall_end:]
    include_begin = server.index('\tgen_serv_include() {\n')
    include_end = server.index('\n\tconfig_load "$NAME"', include_begin)
    server = server[:include_begin] + '''\tgen_serv_include() {
        local FWI
        FWI=$(uci get firewall.shadowsocksr.path 2>/dev/null)
        [ -n "$FWI" ] || return 0
        [ -f "$FWI" ] || printf '#!/bin/sh\\n' >"$FWI"
        printf '\\n/usr/libexec/cudy-ssr-server-firewall reload\\n' >>"$FWI"
        chmod +x "$FWI"
    }
''' + server[include_end:]
    init = init[:begin] + server + init[end:]
    controller_path = package / 'luasrc/controller/shadowsocksr.lua'
    controller = controller_path.read_text(encoding='utf-8')
    controller = once(controller, '''function check_status()
\tlocal e = {}
\tlocal target = luci.http.formvalue("set") or ""
\te.ret = luci.sys.call("curl -m 3 -sS -o /dev/null http://www." .. target .. ".com >/dev/null 2>&1")
\tluci.http.prepare_content("application/json")
\tluci.http.write_json(e)
end''', CHECK_STATUS)
    # Resolve every anchor before writing, so an upstream change never leaves a
    # partly patched package that could proceed to compilation unnoticed.
    for path, content in ((config_path, config), (listing_path, listing), (status_path, status),
                          (init_path, init), (controller_path, controller)):
        path.write_text(content, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
