"""Test the exact patched controller function without running curl or a shell."""
import importlib.util
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime

PROFILE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ss_server_patch', PROFILE / 'patch-ss-server.py')
PATCH = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PATCH)


class ConnectivityTests(unittest.TestCase):
    def probe(self, target, output):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().target = target
        lua.globals().output = output
        lua.execute('''
commands = {}
luci = {
    http = {
        formvalue = function(name) assert(name == 'set'); return target end,
        prepare_content = function(kind) assert(kind == 'application/json') end,
        write_json = function(value) result = value end
    },
    sys = {
        exec = function(command) commands[#commands + 1] = command; return output end,
        call = function() error('This test must never execute a shell') end
    }
}
''')
        lua.execute(PATCH.CHECK_STATUS)
        lua.globals().check_status()
        commands = list(lua.globals().commands.values())
        return lua.globals().result.ret, commands

    def test_google_requires_204(self):
        result, commands = self.probe('google', '204')
        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 1)
        command = commands[0]
        for fragment in ('curl -4 ', '--connect-timeout 4', '--max-time 8',
                         'https://www.google.com/generate_204', "|| printf ' error'"):
            self.assertIn(fragment, command)
        self.assertNotIn('http://', command)
        for code in ('200', '302', '404'):
            with self.subTest(code=code):
                self.assertEqual(self.probe('google', code)[0], 1)

    def test_baidu_accepts_2xx_and_3xx_only(self):
        for code in ('200', '204', '299', '301', '302', '399'):
            with self.subTest(code=code):
                result, commands = self.probe('baidu', code)
                self.assertEqual(result, 0)
                self.assertIn('https://www.baidu.com/', commands[0])
        for code in ('199', '400', '500'):
            with self.subTest(code=code):
                self.assertEqual(self.probe('baidu', code)[0], 1)

    def test_curl_failure_or_invalid_output_is_not_success(self):
        for output in ('', None, '000', '204 error', '200 error', 'HTTP/1.1 204', '204\n200'):
            with self.subTest(output=output):
                self.assertEqual(self.probe('google', output)[0], 1)
        self.assertEqual(self.probe('google', ' 204\n')[0], 0)

    def test_invalid_target_does_not_call_exec_or_call(self):
        for target in (None, '', 'Google', 'example', 'google;echo unsafe', 'baidu.com', '../google'):
            with self.subTest(target=target):
                result, commands = self.probe(target, '204')
                self.assertEqual(result, 1)
                self.assertEqual(commands, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
