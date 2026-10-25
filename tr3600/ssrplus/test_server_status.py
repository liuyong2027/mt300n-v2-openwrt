"""Regress the watcher false positive and preserve actual host server detection."""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime

HERE = Path(__file__).resolve().parent
STATUS = (HERE / 'server-status.lua').read_text(encoding='utf-8')


def row(kind='shadowsocks', enabled='1', port='18301'):
    return {'type': kind, 'enable': enabled, 'server_port': port}


def process(program='xray-server-1', port=18301, protocol='tcp', inode='101',
            owned='101', state=None):
    state = state or ('0A' if protocol.startswith('tcp') else '07')
    return {'command': '/var/etc/ssrplus/bin/' + program + '\0run\0',
            'owned': owned, 'protocol': protocol,
            'socket': f'0: 00000000:{port:04X} 00000000:0000 {state} 0 0 0 0 0 {inode}\n'}


class ServerStatusTests(unittest.TestCase):
    def probe(self, rows=(), global_enable='1', ready=False, processes=()):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().rows = lua.table_from([lua.table_from(item) for item in rows])
        lua.globals().processes = lua.table_from({
            str(index + 100): lua.table_from(item) for index, item in enumerate(processes)})
        lua.globals().global_enable = global_enable
        lua.globals().ready = ready
        lua.execute(r'''
server_run = 0; calls = 0
uci = {}
function uci:get_first(pkg, section, key, default)
    assert(pkg == 'shadowsocksr' and section == 'server_global' and key == 'enable_server')
    return global_enable
end
function uci:foreach(pkg, section, callback)
    assert(pkg == 'shadowsocksr' and section == 'server_config')
    for _, row in ipairs(rows) do callback(row) end
end
luci = {sys = {call = function(command)
    assert(command == '/usr/libexec/cudy-ssr-servers ready >/dev/null 2>&1')
    calls = calls + 1; return ready and 0 or 1
end}}
local function iterator(values)
    local index = 0
    return function() index = index + 1; return values[index] end
end
nixio = {fs = {
    dir = function(path)
        if path == '/proc' then
            local ids = {}; for pid in pairs(processes) do ids[#ids + 1] = pid end
            table.sort(ids); return iterator(ids)
        end
        local pid = path:match('^/proc/(%d+)/fd$')
        if pid and processes[pid] then return iterator({'3'}) end
    end,
    readfile = function(path)
        local pid, kind = path:match('^/proc/(%d+)/(.*)$')
        local process = processes[pid]
        if not process then return nil end
        if kind == 'cmdline' then return process.command end
        if kind == 'net/' .. (process.protocol or '') then return process.socket end
    end,
    readlink = function(path)
        local pid = path:match('^/proc/(%d+)/fd/3$')
        local process = processes[pid]
        if process and process.owned then return 'socket:[' .. process.owned .. ']' end
    end
}}
''')
        lua.execute(STATUS)
        return lua.globals().server_run, lua.globals().calls

    def test_actual_watcher_name_reproduces_old_false_positive(self):
        lua = LuaRuntime()
        self.assertTrue(lua.eval("function() return ('/bin/sh /usr/libexec/cudy-ssr-server-watch'):find('ssr.server') ~= nil end")())
        watcher = {'command': '/bin/sh\0/usr/libexec/cudy-ssr-server-watch\0'}
        self.assertEqual(self.probe([row(enabled='0')], global_enable='0',
                                    processes=[watcher]), (0, 0))
        self.assertEqual(self.probe([row()], processes=[watcher]), (0, 1))

    def test_disabled_or_empty_servers_do_not_become_running(self):
        for rows, enabled in [([], '1'), ([row()], '0'), ([row(enabled='0')], '1'),
                              ([row('socks5', enabled='0')], '1')]:
            with self.subTest(rows=rows, enabled=enabled):
                self.assertEqual(self.probe(rows, global_enable=enabled, ready=True,
                                            processes=[process()]), (0, 0))

    def test_ordinary_ss_uses_real_readiness_including_failed_start(self):
        self.assertEqual(self.probe([row()], ready=True), (1, 1))
        self.assertEqual(self.probe([row()], ready=False, processes=[process()]), (0, 1))

    def test_other_server_types_require_their_own_listener(self):
        for program in ('xray-server-1', 'ssr-server-2', 'ssr-server', 'ss-server',
                        'ss-server-3', 'mihomo-server-4'):
            with self.subTest(program=program):
                self.assertEqual(self.probe([row('socks5')], processes=[process(program)]), (1, 0))
        for change in ({'owned': '999'}, {'port': 18302}, {'state': '01'}):
            with self.subTest(change=change):
                self.assertEqual(self.probe([row('socks5')], processes=[process(**change)]), (0, 0))

    def test_udp_and_ipv6_listeners_are_detected(self):
        for protocol in ('tcp', 'udp', 'tcp6', 'udp6'):
            with self.subTest(protocol=protocol):
                self.assertEqual(self.probe([row('vmess')],
                                            processes=[process(protocol=protocol)]), (1, 0))

    def test_client_watcher_test_command_and_similar_names_are_excluded(self):
        for command in (
            '/usr/bin/xray\0run\0-config\0/var/etc/ssrplus/tcp-udp-ssr-retcp.json\0',
            '/bin/sh\0/usr/libexec/cudy-ssr-server-watch\0',
            '/bin/sh\0-c\0/var/etc/ssrplus/bin/xray-server-1\0',
            '/usr/bin/mihomo\0-f\0/ss-server-1/config.yaml\0',
            '/tmp/xray-server-1\0',
            '/var/etc/ssrplus/bin/xray-server-1-foreign\0',
        ):
            with self.subTest(command=command):
                candidate = process(); candidate['command'] = command
                self.assertEqual(self.probe([row('socks5')], processes=[candidate]), (0, 0))

    def test_unrelated_processes_cannot_supply_each_others_socket(self):
        server = process(owned='102')
        client = process(); client['command'] = '/usr/bin/xray\0'
        self.assertEqual(self.probe([row('socks5')], processes=[server, client]), (0, 0))

    def test_mixed_servers_and_invalid_ports(self):
        self.assertEqual(self.probe([row(), row('socks5')], processes=[process()]), (1, 1))
        for port in ('', '0', '-1', '65536', '18301.5', 'invalid'):
            with self.subTest(port=port):
                self.assertEqual(self.probe([row('socks5', port=port)], processes=[process()]), (0, 0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
