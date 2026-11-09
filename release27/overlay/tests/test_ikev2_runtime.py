#!/usr/bin/env python3
"""Exercise the installed shell helpers against isolated, stateful CLI doubles."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'package/luci-app-mango-ikev2/root'
MOCK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
r = Path(os.environ['FAKE_ROOT'])
f = r / 'fixture.json'
d = json.loads(f.read_text())
n, a = Path(sys.argv[0]).name, sys.argv[1:]
with (r / 'trace').open('a') as out: out.write(json.dumps([n] + a) + '\n')
def save(): f.write_text(json.dumps(d))
if n == 'uci':
    key = a[-1].rsplit('.', 1)[-1]
    if key not in d['uci']: sys.exit(1)
    print(d['uci'][key])
elif n == 'cut': print(d['now'])
elif n == 'swanctl':
    if a[0] == '--list-sas': print((r / 'sas').read_text(), end='')
    elif a[0] == '--load-all': sys.exit(d.get('load_rc', 0))
    elif a[0] == '--initiate':
        if not d.get('dial_ok', False): sys.exit(1)
        p = a[a.index('--ike') + 1]
        (r / 'sas').write_text(f'{p}: #1, ESTABLISHED, IKEv2\n  local id @ 192.0.2.2[4500] [10.0.0.8]\n  {p}: #1, reqid 1, INSTALLED, TUNNEL\n    local  10.0.0.8/32\n')
    elif a[0] == '--terminate':
        p = a[a.index('--ike') + 1]
        lines, show = [], True
        for line in (r / 'sas').read_text().splitlines():
            if line and not line[0].isspace(): show = not line.startswith(p + ': ')
            if show: lines.append(line)
        (r / 'sas').write_text('\n'.join(lines) + '\n')
elif n == 'ip':
    if a[:2] == ['link', 'show']: sys.exit(0)
    elif a[:5] == ['-4', '-o', 'addr', 'show', 'dev']:
        for addr in d['addrs']: print('9: xfrm-mango inet ' + addr + ' scope global xfrm-mango')
    elif a[:3] == ['-4', 'addr', 'flush']: d['addrs'] = []; save()
    elif a[:3] == ['-4', 'addr', 'del']: d['addrs'].remove(a[3]); save()
    elif a[:2] == ['addr', 'replace']: d['addrs'].append(a[2]); save()
    elif a[:3] == ['-4', 'rule', 'show']:
        if d.get('rule'): print('10001: from all fwmark 0x101 lookup 101')
    elif a[:3] == ['-4', 'rule', 'add']: d['rule'] = True; save()
    elif a[:3] == ['-4', 'route', 'replace']:
        if d.get('route_fail'): sys.exit(1)
        if a[3] not in d['routes']: d['routes'].append(a[3])
        save()
elif n == 'ping':
    sys.exit(0 if d.get('esp_ok', True) and '10.0.0.8/32' in d['addrs']
             and all(x in d['routes'] for x in ['default', '1.1.1.1/32', '8.8.8.8/32']) else 1)
elif n == 'mango-ikev2-generate':
    if not d.get('wan_up', True): sys.exit(1)
    print('connections {}')
elif n == 'mango-ikev2-fallback-ssr': sys.exit(d.get('helper_rc', 1))
'''


def sa(peer='mango', installed=True, vip='10.0.0.8'):
    return (f'{peer}: #1, ESTABLISHED, IKEv2\n'
            f'  local id @ 192.0.2.2[4500] [{vip}]\n' +
            (f'  {peer}: #1, reqid 1, INSTALLED, TUNNEL\n    local  {vip}/32\n' if installed else ''))


class Runtime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.r = Path(self.temp.name)
        self.state = self.r / 'state'
        self.state.mkdir()
        self.bin = self.r / 'bin'
        self.bin.mkdir()
        mock = self.r / 'mock'
        mock.write_text(MOCK)
        mock.chmod(0o755)
        for name in ['uci', 'swanctl', 'ip', 'ping', 'cut', 'mango-ikev2-log',
                     'mango-ikev2-generate', 'mango-ikev2-link']:
            (self.bin / name).symlink_to(mock)
        self.mock = mock
        self.d = dict(uci=dict(enabled='1', mode='split', server2='backup1.example.com',
                               server3='backup2.example.com'), now=1000,
                      addrs=['10.0.0.8/32'], routes=[], rule=False)
        self.sas('')
        (self.r / 'trace').touch()
        self.env = dict(os.environ, FAKE_ROOT=str(self.r), MANGO_IKEV2_STATE=str(self.state),
                        PATH=str(self.bin) + ':' + os.environ['PATH'])
        # Relocate only paths in the test copy. No host network or /etc mutation.
        source = (PACKAGE / 'usr/libexec/mango-ikev2-failover').read_text()
        source = source.replace('/usr/libexec/', str(self.bin) + '/')
        source = source.replace('/etc/swanctl/conf.d', str(self.r / 'conf.d'))
        self.script = self.r / 'failover'
        self.script.write_text(source)

    def sas(self, value):
        (self.r / 'sas').write_text(value)

    def run_cycle(self, advance=True):
        (self.r / 'fixture.json').write_text(json.dumps(self.d))
        subprocess.run(['sh', str(self.script)], env=self.env, check=True, timeout=10)
        self.d = json.loads((self.r / 'fixture.json').read_text())
        if advance and (self.state / 'retry-after').exists():
            self.d['now'] = int((self.state / 'retry-after').read_text())

    def trace(self, name=None):
        rows = [json.loads(s) for s in (self.r / 'trace').read_text().splitlines()]
        return [r for r in rows if name is None or r[0] == name]

    def value(self, key):
        return (self.state / key).read_text().strip()

    def status(self):
        text = (PACKAGE / 'usr/libexec/mango-ikev2-status').read_text()
        text = text.replace('/var/etc/mango-ikev2', str(self.state))
        text = text.replace('/var/log/mango-ikev2-events.log', str(self.r / 'events.log'))
        script = self.r / 'status'
        script.write_text(text)
        (self.r / 'fixture.json').write_text(json.dumps(self.d))
        result = subprocess.run(['sh', str(script)], env=self.env, text=True,
                                capture_output=True, check=True)
        return dict(line.split('=', 1) for line in result.stdout.splitlines())

    def test_healthy_repairs_routes_without_deleting_vip(self):
        self.sas(sa())
        for _ in range(3): self.run_cycle()
        self.assertEqual(self.value('fail-count'), '0')
        self.assertEqual(self.d['addrs'], ['10.0.0.8/32'])
        self.assertFalse(any('flush' in r or 'del' in r or '--initiate' in r for r in self.trace()))
        self.assertFalse((self.state / 'retry-after').exists())
        rows = self.trace()
        ping = next(i for i, r in enumerate(rows) if r[0] == 'ping')
        self.assertTrue(any('1.1.1.1/32' in r for r in rows[:ping]))

    def test_default_rotation_all_peers_and_backoff_cap(self):
        peers, delays = [], []
        for _ in range(12):
            now = self.d['now']
            self.run_cycle()
            peers.append(self.value('active'))
            delays.append(int(self.value('retry-after')) - now)
        self.assertEqual(peers, ['mango', 'mango2', 'mango2', 'mango3', 'mango3', 'mango', 'mango', 'mango2', 'mango2', 'mango3', 'mango3', 'mango'])
        self.assertEqual(delays, [30, 30, 60, 60, 120, 120, 240, 240, 300, 300, 300, 300])
        self.assertEqual(len([r for r in self.trace('swanctl') if '--initiate' in r]), 12)

    def test_missing_ssr_helper_does_not_freeze_rotation(self):
        self.d['uci'].update(ssr_fallback='1', ssr_fallback_fails='1')
        for _ in range(6): self.run_cycle()
        self.assertEqual(self.value('active'), 'mango')
        self.assertEqual(self.value('fallback-fail'), '6')

    def test_ssr_failed_helper_continues_rotation(self):
        self.d['uci'].update(ssr_fallback='1', ssr_fallback_fails='1')
        (self.bin / 'mango-ikev2-fallback-ssr').symlink_to(self.mock)
        for _ in range(2): self.run_cycle()
        self.assertEqual(self.value('active'), 'mango2')
        self.assertEqual(len(self.trace('mango-ikev2-fallback-ssr')), 2)

    def test_ssr_unset_threshold_never_runs_helper(self):
        self.d['uci']['ssr_fallback'] = '1'
        (self.bin / 'mango-ikev2-fallback-ssr').symlink_to(self.mock)
        for _ in range(2): self.run_cycle()
        self.assertEqual(self.value('active'), 'mango2')
        self.assertEqual(self.trace('mango-ikev2-fallback-ssr'), [])

    def test_only_successful_explicit_ssr_helper_stops_cycle(self):
        self.d['uci'].update(ssr_fallback='1', ssr_fallback_fails='1')
        self.d['helper_rc'] = 0
        (self.bin / 'mango-ikev2-fallback-ssr').symlink_to(self.mock)
        (self.state / 'fail-count').write_text('1')
        self.run_cycle()
        self.assertEqual(self.value('active'), 'mango')
        self.assertEqual(len(self.trace('mango-ikev2-fallback-ssr')), 1)

    def test_backoff_blocks_extra_dial(self):
        self.run_cycle(advance=False)
        (self.r / 'trace').write_text('')
        self.run_cycle(advance=False)
        self.assertFalse(any('--initiate' in r for r in self.trace()))
        self.assertEqual(self.value('fail-count'), '1')

    def test_dead_esp_cleans_before_redial_and_resets_after_recovery(self):
        self.sas(sa())
        self.d.update(esp_ok=False, dial_ok=False)
        self.run_cycle()
        self.assertTrue(any('flush' in r for r in self.trace('ip')))
        self.assertFalse((self.state / 'logged-up').exists())
        self.d.update(esp_ok=True, dial_ok=True)
        self.run_cycle()
        rows = self.trace()
        dial = next(i for i, r in enumerate(rows) if '--initiate' in r)
        self.assertTrue(any('flush' in r for r in rows[:dial]))
        self.assertEqual(self.value('logged-up'), 'mango')
        self.assertEqual(self.value('fallback-fail'), '0')
        self.assertFalse((self.state / 'retry-after').exists())

    def test_other_peer_child_cannot_make_primary_healthy(self):
        self.sas(sa(installed=False) + sa('mango2', vip='10.9.9.9'))
        self.run_cycle()
        self.assertTrue(any('--initiate' in r for r in self.trace('swanctl')))
        self.assertFalse((self.state / 'logged-up').exists())

    def test_current_peer_vip_and_stale_address_cleanup(self):
        self.sas(sa('mango2', vip='10.9.9.9') + sa())
        self.d['addrs'].append('10.9.9.9/32')
        self.run_cycle()
        self.assertEqual(self.d['addrs'], ['10.0.0.8/32'])
        self.assertTrue(any('10.9.9.9/32' in r and 'del' in r for r in self.trace('ip')))
        self.assertFalse(any('10.0.0.8/32' in r and 'del' in r for r in self.trace('ip')))

    def test_single_peer_retries_without_invented_backup(self):
        self.d['uci'].update(server2='', server3='')
        for _ in range(4): self.run_cycle()
        self.assertEqual(self.value('active'), 'mango')
        self.assertEqual(self.value('fail-count'), '4')

    def test_unready_wan_or_vici_prevents_unbound_dial(self):
        for setting, value in [('wan_up', False), ('load_rc', 1)]:
            self.d[setting] = value
            self.run_cycle()
            self.assertFalse(any('--initiate' in r for r in self.trace('swanctl')))
            self.d[setting] = True if setting == 'wan_up' else 0

    def test_lock_prevents_overlapping_cycle(self):
        with (self.state / 'failover.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_cycle()
        self.assertEqual(self.trace('swanctl'), [])

    def test_disabled_and_direct_do_not_touch_tunnel(self):
        for field, value in [('enabled', '0'), ('mode', 'direct')]:
            self.d['uci'][field] = value
            self.run_cycle()
            self.assertEqual(self.trace('swanctl'), [])
            self.d['uci'][field] = '1' if field == 'enabled' else 'split'

    def test_status_requires_recent_verified_datapath(self):
        self.sas(sa())
        self.assertEqual(self.status()['state'], 'down')
        self.run_cycle()
        self.assertEqual(self.status()['state'], 'up')
        self.d['now'] += 91
        self.assertEqual(self.status()['state'], 'down')
        self.d['esp_ok'] = False
        self.run_cycle()
        self.assertEqual(self.status()['state'], 'down')

    def test_boot_vici_not_ready_keeps_watch_and_installs_dns(self):
        for name in ['mango-ikev2-fw', 'mango-ikev2-watch-start', 'mango-ikev2-dns-on',
                     'swanctl-service', 'sleep']:
            (self.bin / name).symlink_to(self.mock)
        config = self.r / 'config'
        config.mkdir()
        (config / 'cn-cidrs.txt').write_text('1.0.0.0/24\n')
        text = (PACKAGE / 'etc/init.d/mango_ikev2').read_text()
        text = text.replace('CONF_DIR=/var/etc/mango-ikev2', 'CONF_DIR=' + str(self.state))
        text = text.replace('/etc/mango-ikev2', str(config))
        text = text.replace('/etc/swanctl/conf.d', str(self.r / 'conf.d'))
        text = text.replace('/usr/libexec/', str(self.bin) + '/')
        text = text.replace('/etc/init.d/swanctl', str(self.bin / 'swanctl-service'))
        init = self.r / 'init'
        init.write_text(text)
        self.d['load_rc'] = 1
        (self.r / 'fixture.json').write_text(json.dumps(self.d))
        script = '''extra_command() { :; }
. "$1"
mango_ikev2_watch_start() { mango-ikev2-watch-start; }
mango_ikev2_claim_charon() { :; }
mango_ikev2_dns_on() { mango-ikev2-dns-on; }
mango_ikev2_apply
'''
        result = subprocess.run(['sh', '-c', script, 'sh', str(init)], env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.trace('mango-ikev2-watch-start'))
        self.assertTrue(self.trace('mango-ikev2-dns-on'))
        self.assertEqual(len([r for r in self.trace('swanctl') if '--load-all' in r]), 10)
        self.d.update(load_rc=0, dial_ok=True)
        self.run_cycle()
        self.assertEqual(self.value('logged-up'), 'mango')

    def test_wan_reload_does_not_inherit_hotplug_lock(self):
        (self.bin / 'sleep').symlink_to(self.mock)
        stub = self.r / 'reload'
        stub.write_text('''#!/bin/sh
if [ -e /proc/self/fd/7 ]; then
    echo leaked > "$FAKE_ROOT/wan-result"
else
    echo closed > "$FAKE_ROOT/wan-result"
fi
''')
        stub.chmod(0o755)
        source = (PACKAGE / 'etc/hotplug.d/iface/97-mango-ikev2-wan').read_text()
        source = source.replace('/var/lock', str(self.r / 'lock'))
        source = source.replace('/etc/init.d/mango_ikev2', str(stub))
        hotplug = self.r / 'hotplug'
        hotplug.write_text(source)
        (self.r / 'fixture.json').write_text(json.dumps(self.d))
        env = dict(self.env, INTERFACE='wan', ACTION='ifup')
        subprocess.run(['sh', str(hotplug)], env=env, check=True)
        result = self.r / 'wan-result'
        deadline = time.monotonic() + 3
        while not result.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(result.exists(), 'WAN reload did not run')
        self.assertEqual(result.read_text().strip(), 'closed')


if __name__ == '__main__':
    unittest.main(verbosity=2)
