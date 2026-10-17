import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / 'package/luci-app-mango-proxy/root/etc/uci-defaults'
spec = importlib.util.spec_from_file_location('zt_init_patch', ROOT / 'scripts/patch-zerotier-init.py')
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

# The fake implements UCI section existence and batch semantics. It never loads
# host configuration; test scripts receive only a private JSON database and paths.
FAKE_UCI = '''#!/usr/bin/env python3
import json,os,shlex,sys
from pathlib import Path
p=Path(os.environ['UCI_DB']);d=json.loads(p.read_text());a=[x for x in sys.argv[1:] if x!='-q']
def action(a):
 if a[0]=='get':
  if a[1] not in d: sys.exit(1)
  print(d[a[1]]);return
 if a[0]=='set':
  k,v=a[1].split('=',1);d[k]=v
 elif a[0]=='delete': d.pop(a[1],None)
 elif a[0]=='add_list':
  k,v=a[1].split('=',1);d.setdefault(k,[]).append(v)
 elif a[0]!='commit': raise ValueError(a)
if a[0]=='batch':
 for line in sys.stdin.read().splitlines():
  if line.strip():action(shlex.split(line))
else: action(a)
p.write_text(json.dumps(d))
'''


class ZeroTierInitTests(unittest.TestCase):
    def test_pinned_init_only_adds_lifecycle_hooks(self):
        base = (ROOT / 'tests/fixtures/zerotier-5caa62e0.init').read_text()
        out = patcher.patch(base)
        self.assertEqual(out.count('/usr/libexec/mango-zt-direct'), 3)
        self.assertIn('mango-zt-direct stop', out)
        self.assertIn('procd_close_instance\n\t/usr/libexec/mango-zt-direct', out)
        # Identity generation, networks and config options retain their exact code.
        for line in base.splitlines():
            self.assertIn(line, out)
        with self.assertRaises(AssertionError):
            patcher.patch(base + '# changed upstream\n')


@unittest.skipIf(os.name == 'nt' or not shutil.which('sh'), 'Linux shell fixtures run in CI')
class ExistingConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.db = self.path / 'uci.json'
        (self.path / 'uci').write_text(FAKE_UCI)
        (self.path / 'uci').chmod(0o755)
        (self.path / 'logger').write_text('#!/bin/sh\nexit 0\n')
        (self.path / 'logger').chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.path) + os.pathsep + os.environ['PATH'], UCI_DB=str(self.db))

    def run_default(self, name, initial):
        self.db.write_text(json.dumps(initial))
        source = (DEFAULTS / name).read_text()
        source = source.replace('$(cat /tmp/sysinfo/board_name 2>/dev/null)', 'glinet,gl-mt300n-v2')
        source = source.replace('$(cat /tmp/sysinfo/board_name)', 'glinet,gl-mt300n-v2')
        source = source.replace('/etc/zerotier-stable-ports.json', str(self.path / 'ports.json'))
        result = subprocess.run(['sh'], input=source, text=True, env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(self.db.read_text())

    def test_existing_firewall_sections_are_byte_equivalent_in_uci(self):
        before = {}
        for section in ('mango_proxy', 'mango_zt', 'mango_lan_zt', 'mango_mark', 'mango_zt_dns', 'mango_zt_wan'):
            before['firewall.' + section] = 'owner-type'
            before['firewall.' + section + '.enabled'] = '0'
            before['firewall.' + section + '.src_ip'] = '10.23.45.0/24'
        before['firewall.custom'] = 'rule'
        self.assertEqual(self.run_default('95-mango-proxy', before), before)

    def test_fresh_firewall_matches_release21_defaults(self):
        after = self.run_default('95-mango-proxy', {})
        self.assertEqual(after['firewall.mango_zt.forward'], 'REJECT')
        self.assertEqual(after['firewall.mango_zt_dns.dest_port'], '53')
        self.assertEqual(after['firewall.mango_zt_wan.enabled'], '1')

    def test_existing_language_and_led_preserved(self):
        before = {'luci.main.lang': 'en', 'system.wifi_led': 'led', 'system.wifi_led.trigger': 'none'}
        self.assertEqual(self.run_default('96-mango-wifi-led', before), before)
        self.assertEqual(self.run_default('97-mango-language', before), before)

    def test_custom_zerotier_config_identity_and_network_preserved(self):
        custom = self.path / 'custom.json'
        data = b'{"settings":{"secondaryPort":23456,"tertiaryPort":34567,"other":"owner"}}\n'
        custom.write_bytes(data)
        before = {'zerotier.global': 'zerotier', 'zerotier.global.enabled': '1',
                  'zerotier.global.local_conf_path': str(custom), 'zerotier.global.secret': 'fixture-identity',
                  'zerotier.network1.id': '0123456789abcdef', 'mango_proxy.main.mode': 'split',
                  'firewall.custom.enabled': '0'}
        after = self.run_default('96-mango-zt-direct', before)
        for k, v in before.items(): self.assertEqual(after[k], v)
        self.assertEqual(custom.read_bytes(), data)
        self.assertFalse((self.path / 'ports.json').exists())
        self.assertEqual(after['firewall.mango_zt_direct.path'], '/usr/libexec/mango-zt-direct')
        self.assertEqual(self.run_default('96-mango-zt-direct', after), after)

    def test_new_config_does_not_enable_zerotier(self):
        before = {'zerotier.global.enabled': '0'}
        after = self.run_default('96-mango-zt-direct', before)
        self.assertEqual(after['zerotier.global.enabled'], '0')
        settings = json.loads((self.path / 'ports.json').read_text())['settings']
        self.assertEqual((settings['secondaryPort'], settings['tertiaryPort']), (48170, 20089))

    def test_owner_disabled_include_remains_disabled(self):
        before = {'zerotier.global.local_conf_path': '/owner/path.json',
                  'firewall.mango_zt_direct': 'include', 'firewall.mango_zt_direct.enabled': '0',
                  'firewall.mango_zt_direct.path': '/usr/libexec/mango-zt-direct'}
        self.assertEqual(self.run_default('96-mango-zt-direct', before), before)


if __name__ == '__main__':
    unittest.main()
