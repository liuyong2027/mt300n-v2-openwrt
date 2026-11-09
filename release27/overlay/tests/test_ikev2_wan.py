#!/usr/bin/env python3
"""Test actual Lua generation and WAN link setup without a router or secrets."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'package/luci-app-mango-ikev2/root'


class Wan(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.r = Path(self.temp.name)
        network = self.r / 'network.sh'
        network.write_text('''network_flush_cache() { :; }
network_get_ipaddr() { [ -n "$FAKE_WAN_IP" ] || return 1; eval "$1=\\$FAKE_WAN_IP"; }
network_get_device() { [ -n "$FAKE_WAN_DEVICE" ] || return 1; eval "$1=\\$FAKE_WAN_DEVICE"; }
''')
        self.env = dict(os.environ, FAKE_WAN_IP='192.0.2.10', FAKE_WAN_DEVICE='pppoe-wan')
        text = (PACKAGE / 'usr/libexec/mango-ikev2-generate').read_text()
        text = text.replace('/lib/functions/network.sh', str(network))
        text = text.replace('/usr/lib/mango-ikev2/model.lua', str(PACKAGE / 'usr/lib/mango-ikev2/model.lua'))
        self.generator = self.r / 'generate.lua'
        self.generator.write_text(text)
        self.link = self.r / 'link'
        self.link.write_text((PACKAGE / 'usr/libexec/mango-ikev2-link').read_text().replace('/lib/functions/network.sh', str(network)))
        self.p = dict(enabled='1', mode='split', server='vpn.example.com', auth='eap',
                      username='test-user', password='test-password',
                      server2='backup1.example.com', server3='backup2.example.com')

    def generate(self):
        # Lua table literals for controlled fixture strings only.
        fields = ','.join('[' + json.dumps(k) + ']=' + json.dumps(v) for k, v in self.p.items())
        script = "package.preload['uci']=function() return {cursor=function() return {get_all=function() return {" + fields + "} end} end} end; arg={'swanctl'}; dofile(" + json.dumps(str(self.generator)) + ')'
        return subprocess.run(['lua5.1', '-e', script], env=self.env, text=True, capture_output=True)

    def test_netifd_wan_binds_all_peers_and_disables_mobike(self):
        for address in ['192.0.2.10', '198.51.100.22']:
            self.env['FAKE_WAN_IP'] = address
            result = self.generate()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count('local_addrs = ' + address), 3)
            self.assertEqual(result.stdout.count('mobike = no'), 3)

    def test_missing_or_invalid_wan_cannot_dial_from_vip(self):
        for address in ['', '%any', '192.0.2.10/24', '999.1.1.1', '1.2.3.4\n5.6.7.8']:
            self.env['FAKE_WAN_IP'] = address
            result = self.generate()
            self.assertNotEqual(result.returncode, 0, address)
            self.assertEqual(result.stdout, '')

    def test_runtime_device_instead_of_static_ethernet_guess(self):
        bindir = self.r / 'bin'
        bindir.mkdir()
        ip = bindir / 'ip'
        ip.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_IP_LOG"\ncase "$*" in "link show "*) exit 1;; esac\n')
        ip.chmod(0o755)
        uci = bindir / 'uci'
        uci.write_text('#!/bin/sh\nexit 1\n')
        uci.chmod(0o755)
        log = self.r / 'ip.log'
        self.env.update(PATH=str(bindir) + ':' + self.env['PATH'], FAKE_IP_LOG=str(log))
        subprocess.run(['sh', str(self.link)], env=self.env, check=True)
        self.assertIn('type xfrm dev pppoe-wan if_id 42', log.read_text())
        log.write_text('')
        self.env['FAKE_WAN_DEVICE'] = ''
        self.assertNotEqual(subprocess.run(['sh', str(self.link)], env=self.env).returncode, 0)
        self.assertEqual(log.read_text(), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
