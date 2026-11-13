#!/usr/bin/env python3
"""Test actual Lua generation and WAN link setup without a router or secrets."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
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


class WanHotplug(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.r = Path(self.temp.name)
        self.bin = self.r / 'bin'
        self.bin.mkdir()
        self.state = self.r / 'state'
        self.state.mkdir()
        (self.r / 'lock').mkdir()
        network = self.r / 'network.sh'
        network.write_text('network_flush_cache() { :; }\n'
                           'network_get_ipaddr() { [ -n "$FAKE_WAN_IP" ] || return 1; eval "$1=\\$FAKE_WAN_IP"; }\n')
        (self.bin / 'uci').write_text('#!/bin/sh\nkey=${3##*.}\ncase "$key" in enabled) echo 1;; mode) echo split;; *) exit 1;; esac\n')
        (self.bin / 'ubus').write_text('#!/bin/sh\nexit 0\n')
        (self.bin / 'jsonfilter').write_text('#!/bin/sh\nprintf "%s\\n" "$FAKE_WAN_UP"\n')
        (self.bin / 'logger').write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_LOGGER"\n')
        reload = self.r / 'reload'
        reload.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_RELOAD"\n')
        for path in list(self.bin.iterdir()) + [reload]:
            path.chmod(0o755)
        text = (PACKAGE / 'etc/hotplug.d/iface/97-mango-ikev2-wan').read_text()
        text = text.replace('/lib/functions/network.sh', str(network))
        text = text.replace('/var/lock', str(self.r / 'lock'))
        text = text.replace('/var/etc/mango-ikev2', str(self.state))
        text = text.replace('/etc/init.d/mango_ikev2', str(reload))
        # The two-second settle is not what these cases decide.
        text = text.replace('sleep 2', 'sleep 0')
        self.script = self.r / 'hotplug'
        self.script.write_text(text)
        self.script.chmod(0o755)
        # A function overrides BusyBox ash's standalone logger applet.
        wrapper = self.r / 'wrap'
        wrapper.write_text('logger() { printf "%s\\n" "$*" >> "$FAKE_LOGGER"; }\n. "$1"\n')
        wrapper.chmod(0o755)
        self.wrapper = wrapper
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        FAKE_WAN_IP='192.0.2.10', FAKE_WAN_UP='10000',
                        FAKE_LOGGER=str(self.r / 'logger.log'),
                        FAKE_RELOAD=str(self.r / 'reload.log'))

    def write_conf(self, addresses, age):
        conf = self.state / 'swanctl.conf'
        conf.write_text(''.join('    local_addrs = %s\n' % address for address in addresses))
        when = time.time() - age
        os.utime(conf, (when, when))

    def run_hotplug(self, action='ifup', addresses='0', shell=('sh',)):
        for name in ('logger.log', 'reload.log'):
            path = self.r / name
            if path.exists():
                path.unlink()
        env = dict(self.env, INTERFACE='wan', ACTION=action, IFUPDATE_ADDRESSES=addresses)
        subprocess.run(list(shell) + [str(self.wrapper), str(self.script)], env=env, check=True, timeout=10)
        deadline = time.time() + 3
        while time.time() < deadline and not (self.r / 'reload.log').exists() and not (self.r / 'logger.log').exists():
            time.sleep(0.02)
        # The helper is backgrounded; give a matching decision time to finish.
        time.sleep(0.1)

    def assert_skipped(self, shell=('sh',)):
        self.run_hotplug(shell=shell)
        self.assertFalse((self.r / 'reload.log').exists(), shell)
        self.assertIn('config already bound to 192.0.2.10', (self.r / 'logger.log').read_text())

    def assert_reloaded(self, action='ifup', addresses='0', shell=('sh',)):
        self.run_hotplug(action=action, addresses=addresses, shell=shell)
        self.assertEqual((self.r / 'reload.log').read_text().strip(), 'reload')
        self.assertFalse((self.r / 'logger.log').exists())

    def test_fresh_matching_config_skips_reload(self):
        self.write_conf(['192.0.2.10', '192.0.2.10', '192.0.2.10'], age=1)
        for shell in self.shells():
            with self.subTest(shell=shell):
                self.assert_skipped(shell)

    def test_older_config_reloads(self):
        self.write_conf(['192.0.2.10'], age=10000)
        self.env['FAKE_WAN_UP'] = '30'
        for shell in self.shells():
            with self.subTest(shell=shell):
                self.assert_reloaded(shell=shell)

    def test_different_address_reloads(self):
        self.write_conf(['192.0.2.10', '198.51.100.22'], age=1)
        for shell in self.shells():
            with self.subTest(shell=shell):
                self.assert_reloaded(shell=shell)

    def test_ifupdate_reloads_even_when_config_is_fresh(self):
        self.write_conf(['192.0.2.10'], age=1)
        for shell in self.shells():
            with self.subTest(shell=shell):
                self.assert_reloaded(action='ifupdate', addresses='1', shell=shell)

    def test_missing_config_reloads(self):
        for shell in self.shells():
            with self.subTest(shell=shell):
                self.assert_reloaded(shell=shell)

    def shells(self):
        shells = [('sh',)]
        if Path('/usr/bin/busybox').exists():
            shells.append(('busybox', 'ash'))
        return shells


if __name__ == '__main__':
    unittest.main(verbosity=2)
