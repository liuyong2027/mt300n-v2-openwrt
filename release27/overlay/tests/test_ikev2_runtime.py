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
import json, os, re, sys
from pathlib import Path
r = Path(os.environ['FAKE_ROOT'])
f = r / 'fixture.json'
d = json.loads(f.read_text())
n, a = Path(sys.argv[0]).name, sys.argv[1:]
with (r / 'trace').open('a') as out: out.write(json.dumps([n] + a) + '\n')
def save(): f.write_text(json.dumps(d))
def remove_sa(identifier):
    lines, show = [], True
    for line in (r / 'sas').read_text().splitlines():
        match = re.match(r'^(\S+): #(\d+),', line)
        if match:
            show = match.group(2) != identifier if identifier.isdigit() else match.group(1) != identifier
        if show: lines.append(line)
    (r / 'sas').write_text('\n'.join(lines) + '\n')
if n == 'uci':
    key = a[-1].rsplit('.', 1)[-1]
    if key not in d['uci']: sys.exit(1)
    print(d['uci'][key])
elif n == 'cut': print(d['now'])
elif n == 'swanctl':
    if a[0] == '--list-sas':
        if d.get('list_rc') or (d.get('term_seen') and d.get('list_fail_after_terminate')): sys.exit(1)
        d['list_reads'] = d.get('list_reads', 0) + 1
        if d.get('sas_on_read') == d['list_reads']:
            (r / 'sas').write_text(d['next_sas'])
        save()
        if d.get('pending_id'):
            d['delete_reads'] -= 1
            if d['delete_reads'] <= 0:
                remove_sa(d.pop('pending_id'))
            save()
        print((r / 'sas').read_text(), end='')
    elif a[0] == '--load-all': sys.exit(d.get('load_rc', 0))
    elif a[0] == '--initiate':
        if d.get('list_fail_after_init'): d['list_rc'] = 1; save()
        full = '--ike' in a
        if d.get('init_transition'):
            peer = a[a.index('--ike' if full else '--child') + 1]
            if d['init_transition'] == 'CONNECTING':
                (r / 'sas').write_text(f'{peer}: #1, CONNECTING, IKEv2\n')
            else:
                (r / 'sas').write_text(f'{peer}: #1, ESTABLISHED, IKEv2\n  local id @ 192.0.2.2[4500] [10.0.0.8]\n  {peer}: #1, reqid 1, REKEYED, TUNNEL\n    local  10.0.0.8/32\n')
            sys.exit(1)
        if not d.get('full_ok' if full else 'child_ok', d.get('dial_ok', False)): sys.exit(1)
        if '--ike' in a:
            p = a[a.index('--ike') + 1]
        elif '--child' in a:
            p = a[a.index('--child') + 1]
        else:
            sys.exit(1)
        vip = d.get('dial_vip', '10.0.0.8')
        uid = {'mango': 1, 'mango2': 2, 'mango3': 3}[p]
        remove_sa(p)
        with (r / 'sas').open('a') as out: out.write(f'{p}: #{uid}, ESTABLISHED, IKEv2\n  local id @ 192.0.2.2[4500] [{vip}]\n  {p}: #1, reqid 1, INSTALLED, TUNNEL\n    local  {vip}/32\n')
    elif a[0] == '--terminate':
        d['term_seen'] = True
        mode = d.get('terminate_mode', 'normal')
        save()
        if mode == 'stuck': sys.exit(1)
        if mode == 'force_only' and '--force' not in a: sys.exit(0)
        identifier = a[a.index('--ike-id' if '--ike-id' in a else '--ike') + 1]
        if mode == 'deferred' and '--force' not in a:
            d.update(pending_id=identifier, delete_reads=2); save()
        else:
            remove_sa(identifier)
            if mode == 'new_sa':
                with (r / 'sas').open('a') as out: out.write('mango: #99, ESTABLISHED, IKEv2\n')
        sys.exit(d.get('terminate_rc', 0))
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
elif n == 'curl':
    connected = ('10.0.0.8/32' in d['addrs'] and all(x in d['routes'] for x in ['default', '1.1.1.1/32', '8.8.8.8/32']))
    endpoint = a[a.index('--resolve') + 1]
    ok = d.get('https_ok', False) and endpoint not in d.get('https_fail_endpoints', [])
    if not (connected and ok): print('000', end=''); sys.exit(1)
    print(d.get('http_code', '204'), end='')
elif n == 'mango-ikev2-generate':
    if not d.get('wan_up', True): sys.exit(1)
    print('connections {}')
elif n == 'mango-ikev2-fallback-ssr': sys.exit(d.get('helper_rc', 1))
'''


def sa(peer='mango', installed=True, vip='10.0.0.8', child_state='INSTALLED'):
    uid = {'mango': 1, 'mango2': 2, 'mango3': 3}[peer]
    text = (f'{peer}: #{uid}, ESTABLISHED, IKEv2\n'
            f'  local id @ 192.0.2.2[4500] [{vip}]\n')
    if installed:
        text += (f'  {peer}: #1, reqid 1, {child_state}, TUNNEL\n'
                 f'    local  {vip}/32\n')
    return text


def sa_rekeyed_only(peer='mango', vip='10.0.0.8'):
    """IKE up with only a REKEYED child — the rekey window before INSTALLED."""
    uid = {'mango': 1, 'mango2': 2, 'mango3': 3}[peer]
    return (f'{peer}: #{uid}, ESTABLISHED, IKEv2\n'
            f'  local id @ 192.0.2.2[4500] [{vip}]\n'
            f'  {peer}: #1, reqid 1, REKEYED, TUNNEL\n'
            f'    local  {vip}/32\n')


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
                     'mango-ikev2-generate', 'mango-ikev2-link', 'curl', 'sleep']:
            (self.bin / name).symlink_to(mock)
        cleanup = self.bin / 'mango-ikev2-cleanup'
        cleanup.write_text((PACKAGE / 'usr/libexec/mango-ikev2-cleanup').read_text())
        cleanup.chmod(0o755)
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
        for _ in range(16):
            now = self.d['now']
            self.run_cycle()
            peers.append(self.value('active'))
            delays.append(int(self.value('retry-after')) - now)
        self.assertEqual(peers, ['mango', 'mango2', 'mango2', 'mango3', 'mango3', 'mango', 'mango', 'mango2', 'mango2', 'mango3', 'mango3', 'mango', 'mango', 'mango2', 'mango2', 'mango3'])
        self.assertEqual(delays, [30, 30, 30, 60, 60, 60, 120, 120, 120, 240, 240, 240, 300, 300, 300, 300])
        self.assertEqual(len([r for r in self.trace('swanctl') if '--initiate' in r]), 16)

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

    def test_dead_esp_reinitiates_child_without_flush(self):
        self.sas(sa())
        self.d.update(esp_ok=False, dial_ok=False)
        for _ in range(3): self.run_cycle()
        self.assertFalse(any('flush' in r for r in self.trace('ip')))
        self.assertTrue(any('--initiate' in r and '--child' in r and '--ike' not in r
                            for r in self.trace('swanctl')))
        self.assertFalse((self.state / 'logged-up').exists())
        self.d.update(esp_ok=True, dial_ok=True)
        (self.r / 'trace').write_text('')
        self.run_cycle()
        # After backoff, child repair should succeed without VIP flush.
        self.assertFalse(any('flush' in r for r in self.trace('ip')))
        self.assertEqual(self.value('logged-up'), 'mango')
        self.assertEqual(self.value('fallback-fail'), '0')
        self.assertFalse((self.state / 'retry-after').exists())

    def test_rekey_window_skips_without_flush_or_dial(self):
        self.sas(sa_rekeyed_only())
        self.d['addrs'] = ['10.0.0.8/32']
        self.run_cycle()
        self.assertFalse(any('flush' in r for r in self.trace('ip')))
        self.assertFalse(any('--initiate' in r for r in self.trace('swanctl')))
        self.assertEqual(self.d['addrs'], ['10.0.0.8/32'])

    def test_ike_up_missing_child_with_vip_initiates_child_only(self):
        # IKE line still carries [vip] even when CHILD is gone.
        self.sas(sa(installed=False))
        self.d.update(dial_ok=True, esp_ok=True, addrs=[])
        self.run_cycle()
        inits = [r for r in self.trace('swanctl') if '--initiate' in r]
        self.assertTrue(inits)
        self.assertTrue(all('--child' in r and '--ike' not in r for r in inits))
        self.assertFalse(any('flush' in r for r in self.trace('ip')))
        self.assertEqual(self.value('logged-up'), 'mango')

    def test_orphan_ike_without_vip_full_redials(self):
        # INTERNAL_ADDRESS_FAILURE leaves ESTABLISHED IKE with only [4500], no VIP.
        self.sas('mango: #1, ESTABLISHED, IKEv2\n'
                 "  local  '192.0.2.2' @ 192.0.2.2[4500]\n")
        self.d.update(dial_ok=True, esp_ok=True, addrs=['10.0.0.8/32'])
        self.run_cycle()
        terms = [r for r in self.trace('swanctl') if '--terminate' in r and '--ike-id' in r]
        self.assertTrue(terms)
        inits = [r for r in self.trace('swanctl') if '--initiate' in r]
        self.assertTrue(any('--ike' in r for r in inits))
        self.assertTrue(any('flush' in r for r in self.trace('ip')))
        self.assertEqual(self.value('logged-up'), 'mango')

    def test_peer_vip_ignores_udp_port_brackets(self):
        self.sas('mango: #1, ESTABLISHED, IKEv2\n'
                 "  local  '192.0.2.2' @ 192.0.2.2[4500]\n"
                 '  mango: #1, reqid 1, INSTALLED, TUNNEL\n'
                 '    local  10.0.0.8/32\n')
        self.d.update(esp_ok=True, addrs=['10.0.0.8/32'])
        self.run_cycle()
        self.assertFalse(any('4500/32' in r for r in self.trace('ip')))
        self.assertEqual(self.d['addrs'], ['10.0.0.8/32'])
        self.assertEqual(self.value('logged-up'), 'mango')

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

    def test_icmp_blocked_https_healthy_does_not_repair(self):
        self.sas(sa())
        self.d.update(esp_ok=False, https_ok=True)
        self.env['HTTPS_PROXY'] = 'http://unusable-proxy.example:8080'
        for _ in range(4): self.run_cycle()
        self.assertEqual(self.value('logged-up'), 'mango')
        self.assertFalse(any('--initiate' in row or '--terminate' in row
                             for row in self.trace('swanctl')))
        self.assertFalse((self.state / 'probe-fail-mango').exists())
        for row in self.trace('curl'):
            self.assertEqual(row[row.index('--interface') + 1], 'xfrm-mango')
            self.assertEqual(row[row.index('--noproxy') + 1], '*')
            self.assertEqual(row[row.index('--proto') + 1], '=https')
            self.assertIn('--resolve', row)
            self.assertNotIn('--insecure', row)
            self.assertNotIn('-k', row)
            self.assertNotIn('--location', row)

    def test_second_https_endpoint_can_confirm_datapath(self):
        self.sas(sa())
        self.d.update(esp_ok=False, https_ok=True,
                      https_fail_endpoints=['cloudflare-dns.com:443:1.1.1.1'])
        self.run_cycle()
        self.assertEqual(self.value('logged-up'), 'mango')
        self.assertEqual(len(self.trace('curl')), 2)
        self.assertIn('dns.google:443:8.8.8.8', self.trace('curl')[-1])

    def test_unhealthy_https_status_is_not_a_success(self):
        self.sas(sa())
        self.d.update(esp_ok=False, https_ok=True, http_code='503')
        self.run_cycle()
        self.assertFalse((self.state / 'logged-up').exists())
        self.assertEqual(self.value('probe-fail-mango'), '1')
        self.assertFalse(any('--initiate' in row for row in self.trace('swanctl')))

    def test_three_bad_probe_cycles_before_first_child_repair(self):
        self.sas(sa())
        self.d['esp_ok'] = False
        for _ in range(2):
            self.run_cycle()
            self.d['now'] += 30
            self.assertFalse(any('--initiate' in row for row in self.trace('swanctl')))
            self.assertFalse((self.state / 'fallback-fail').exists())
        self.run_cycle()
        repairs = [row for row in self.trace('swanctl') if '--initiate' in row]
        self.assertEqual(len(repairs), 1)
        self.assertNotIn('--ike', repairs[0])
        self.assertEqual(self.value('fallback-fail'), '1')
        self.assertFalse(any('flush' in row for row in self.trace('ip')))
        probe = [row for row in self.trace('mango-ikev2-log')
                 if 'tunnel probes failed' in row[-1]]
        self.assertEqual([(row[1], row[-1]) for row in probe], [
            ('warn', 'tunnel probes failed (1/3)'),
            ('warn', 'tunnel probes failed (2/3)'),
            ('fail', 'tunnel probes failed (3/3)'),
        ])
        fail_at = next(i for i, row in enumerate(self.trace())
                       if row[0] == 'mango-ikev2-log' and row[-1].endswith('(3/3)'))
        repair_at = next(i for i, row in enumerate(self.trace())
                         if row[0] == 'swanctl' and '--initiate' in row)
        self.assertLess(fail_at, repair_at)

    def test_same_peer_probe_recovery_logs_one_ok_and_clean_cycles_do_not(self):
        self.sas(sa())
        self.run_cycle()
        self.assertEqual(
            [(row[1], row[-1]) for row in self.trace('mango-ikev2-log') if row[1] == 'ok'],
            [('ok', 'connected vip=10.0.0.8')])
        (self.r / 'trace').write_text('')
        self.run_cycle()
        self.assertEqual(self.trace('mango-ikev2-log'), [])

        self.d['esp_ok'] = False
        self.run_cycle()
        self.run_cycle()
        self.assertEqual(
            [(row[1], row[-1]) for row in self.trace('mango-ikev2-log')],
            [('warn', 'tunnel probes failed (1/3)'),
             ('warn', 'tunnel probes failed (2/3)')])
        self.assertFalse(any('--initiate' in row for row in self.trace('swanctl')))

        self.d['esp_ok'] = True
        (self.r / 'trace').write_text('')
        self.run_cycle()
        self.assertEqual(
            [(row[1], row[-1]) for row in self.trace('mango-ikev2-log')],
            [('ok', 'probe recovered after 2 failed')])
        self.assertFalse((self.state / 'probe-fail-mango').exists())
        (self.r / 'trace').write_text('')
        self.run_cycle()
        self.assertEqual(self.trace('mango-ikev2-log'), [])

    def test_warn_does_not_move_last_fail_and_recovery_moves_last_ok(self):
        log = self.r / 'events.log'
        log.write_text(
            '2026-11-12 08:00:00\tok\t主服务器\tvpn\tid\tconnected vip=10.0.0.8\n'
            '2026-11-13 09:00:00\twarn\t主服务器\tvpn\tid\ttunnel probes failed (1/3)\n'
            '2026-11-13 09:00:30\twarn\t主服务器\tvpn\tid\ttunnel probes failed (2/3)\n')
        status = self.status()
        self.assertEqual(status['last_ok'], '2026-11-12 08:00:00')
        self.assertEqual(status['last_fail'], '')
        self.assertEqual(status['last_switch'], '')
        log.write_text(log.read_text() +
            '2026-11-13 09:01:00\tfail\t主服务器\tvpn\tid\ttunnel probes failed (3/3)\n'
            '2026-11-13 09:02:00\tok\t主服务器\tvpn\tid\tprobe recovered after 1 failed\n'
            '2026-11-13 09:03:00\tswitch\t备用服务器1\tvpn\tid\t节点切换 主服务器 → 备用服务器1\n')
        status = self.status()
        self.assertEqual(status['last_ok'], '2026-11-13 09:02:00')
        self.assertEqual(status['last_fail'], '2026-11-13 09:01:00')
        self.assertEqual(status['last_switch'], '2026-11-13 09:03:00')
        self.assertIn('节点切换', status['last_switch_detail'])

    def test_success_breaks_probe_failure_streak(self):
        self.sas(sa())
        self.d['esp_ok'] = False
        for _ in range(2): self.run_cycle()
        self.d['https_ok'] = True
        self.run_cycle()
        self.assertFalse((self.state / 'probe-fail-mango').exists())
        self.d['https_ok'] = False
        for _ in range(2): self.run_cycle()
        self.assertFalse(any('--initiate' in row for row in self.trace('swanctl')))
        self.assertEqual(self.value('probe-fail-mango'), '2')

    def test_new_child_without_datapath_proof_is_debounced(self):
        self.d.update(full_ok=True, esp_ok=False)
        self.run_cycle()
        self.assertEqual(self.value('probe-fail-mango'), '1')
        self.assertFalse((self.state / 'fallback-fail').exists())
        self.assertFalse((self.state / 'health-up').exists())
        self.run_cycle()
        self.assertFalse(any('--child' in row and '--ike' not in row
                             for row in self.trace('swanctl') if '--initiate' in row))

    def test_single_peer_gets_one_full_recovery_then_cooldown(self):
        self.d['uci'].update(server2='', server3='')
        self.sas(sa())
        self.d.update(esp_ok=False, child_ok=False, full_ok=True)
        # Two probe grace cycles, three failed CHILD attempts, then full recovery.
        for _ in range(6): self.run_cycle()
        full = lambda: [row for row in self.trace('swanctl')
                        if '--initiate' in row and '--ike' in row]
        self.assertEqual(len(full()), 1)
        deadline = int(self.value('full-after-mango'))
        self.assertEqual(deadline - self.d['now'], 300)
        # The new CHILD still has no datapath. It must not be torn down each tick.
        for _ in range(4): self.run_cycle()
        self.assertTrue((self.state / 'full-pending-mango').exists())
        self.d['now'] = deadline - 1
        self.run_cycle(advance=False)
        self.assertEqual(len(full()), 1)
        self.d['now'] = deadline
        self.run_cycle(advance=False)
        self.assertEqual(len(full()), 2)
        self.assertEqual(int(self.value('full-after-mango')), deadline + 300)

    def test_healthy_cycle_keeps_full_recovery_rate_limit(self):
        self.sas(sa())
        (self.state / 'full-after-mango').write_text('1300')
        (self.state / 'full-pending-mango').write_text('1')
        (self.state / 'child-fail-mango').write_text('3')
        self.run_cycle()
        self.assertEqual(self.value('full-after-mango'), '1300')
        self.assertFalse((self.state / 'full-pending-mango').exists())
        self.assertFalse((self.state / 'child-fail-mango').exists())

    def test_repair_and_full_failures_share_tripled_backoff(self):
        self.sas(sa())
        self.d['esp_ok'] = False
        for _ in range(2): self.run_cycle()
        delays = []
        for _ in range(4):
            now = self.d['now']
            self.run_cycle()
            delays.append(int(self.value('retry-after')) - now)
        self.assertEqual(delays, [30, 30, 30, 60])

    def orphan(self):
        self.sas('mango: #1, ESTABLISHED, IKEv2\n  local id @ 192.0.2.2[4500]\n')

    def test_stuck_termination_never_flushes_or_redials(self):
        self.orphan()
        self.d['terminate_mode'] = 'stuck'
        self.run_cycle()
        terms = [row for row in self.trace('swanctl') if '--terminate' in row]
        self.assertEqual(len(terms), 2)
        self.assertIn('--force', terms[-1])
        self.assertTrue(all('--ike-id' in row for row in terms))
        self.assertIn('ESTABLISHED', (self.r / 'sas').read_text())
        self.assertFalse(any('flush' in row for row in self.trace('ip')))
        self.assertFalse(any('--initiate' in row for row in self.trace('swanctl')))

    def test_force_cleanup_is_verified_before_vip_flush(self):
        self.orphan()
        self.d.update(terminate_mode='force_only', dial_ok=True)
        self.run_cycle()
        rows = self.trace()
        force = next(i for i, row in enumerate(rows) if '--force' in row)
        flush = next(i for i, row in enumerate(rows) if row[0] == 'ip' and 'flush' in row)
        initiate = next(i for i, row in enumerate(rows) if '--initiate' in row)
        self.assertLess(force, flush)
        self.assertLess(flush, initiate)
        self.assertTrue(any('--list-sas' in row for row in rows[force + 1:flush]))

    def test_async_termination_is_polled_without_unneeded_force(self):
        self.orphan()
        self.d.update(terminate_mode='deferred', dial_ok=True)
        self.run_cycle()
        rows = self.trace()
        term = next(i for i, row in enumerate(rows) if '--terminate' in row)
        flush = next(i for i, row in enumerate(rows) if row[0] == 'ip' and 'flush' in row)
        self.assertGreaterEqual(sum('--list-sas' in row for row in rows[term + 1:flush]), 2)
        self.assertFalse(any('--force' in row for row in rows))

    def test_sa_query_failure_is_not_treated_as_empty(self):
        self.sas(sa())
        self.d['list_rc'] = 1
        self.run_cycle()
        self.assertFalse(any('--terminate' in row or '--initiate' in row
                             for row in self.trace('swanctl')))
        self.assertEqual(self.trace('ip'), [])

    def test_query_error_after_terminate_blocks_flush_and_force(self):
        self.orphan()
        self.d['list_fail_after_terminate'] = True
        self.run_cycle()
        self.assertFalse(any('--force' in row for row in self.trace('swanctl')))
        self.assertFalse(any('flush' in row for row in self.trace('ip')))
        self.assertFalse(any('--initiate' in row for row in self.trace('swanctl')))

    def test_new_sa_during_cleanup_is_not_killed_or_ignored(self):
        self.orphan()
        self.d['terminate_mode'] = 'new_sa'
        self.run_cycle()
        self.assertIn('mango: #99,', (self.r / 'sas').read_text())
        self.assertFalse(any('--ike-id' in row and '99' in row for row in self.trace('swanctl')))
        self.assertFalse(any('flush' in row for row in self.trace('ip')))
        self.assertFalse(any('--initiate' in row for row in self.trace('swanctl')))

    def test_multiple_old_sa_ids_are_all_confirmed_gone(self):
        self.orphan()
        with (self.r / 'sas').open('a') as out:
            out.write('mango: #11, ESTABLISHED, IKEv2\n')
        self.d['dial_ok'] = True
        self.run_cycle()
        ids = [row[row.index('--ike-id') + 1] for row in self.trace('swanctl')
               if '--terminate' in row]
        self.assertEqual(ids, ['1', '11'])
        self.assertEqual(self.value('logged-up'), 'mango')

    def test_cleanup_does_not_touch_unmanaged_connection(self):
        self.sas('other: #8, ESTABLISHED, IKEv2\n')
        self.d['dial_ok'] = True
        self.run_cycle()
        self.assertIn('other: #8,', (self.r / 'sas').read_text())
        self.assertFalse(any('--ike-id' in row and '8' in row for row in self.trace('swanctl')))
        self.assertEqual(self.value('logged-up'), 'mango')

    def test_connecting_grace_is_bounded_and_respects_retry_after_cleanup(self):
        self.sas('mango: #1, CONNECTING, IKEv2\n')
        self.run_cycle(advance=False)
        self.assertEqual(self.value('transition-mango'), '1000 connecting')
        self.d['now'] = 1059
        self.run_cycle(advance=False)
        self.assertFalse(any('--terminate' in row for row in self.trace('swanctl')))
        self.d['now'] = 1060
        self.run_cycle(advance=False)
        self.assertTrue(any('--terminate' in row for row in self.trace('swanctl')))
        self.assertFalse(any('--initiate' in row for row in self.trace('swanctl')))
        self.assertFalse(any('flush' in row for row in self.trace('ip')))
        self.assertEqual(self.value('retry-after'), '1090')
        self.d.update(now=1090, dial_ok=True)
        self.run_cycle()
        self.assertEqual(self.value('logged-up'), 'mango')

    def test_rekey_state_changes_do_not_restart_grace_clock(self):
        self.sas(sa_rekeyed_only())
        self.run_cycle(advance=False)
        self.d['now'] = 1100
        self.sas(sa_rekeyed_only().replace('REKEYED', 'DELETING'))
        self.run_cycle(advance=False)
        self.assertEqual(self.value('transition-mango'), '1000 transition')
        self.assertFalse(any('--terminate' in row for row in self.trace('swanctl')))
        self.d['now'] = 1120
        self.run_cycle(advance=False)
        self.assertTrue(any('--terminate' in row for row in self.trace('swanctl')))
        self.assertFalse(any('flush' in row for row in self.trace('ip')))
        self.assertEqual(self.value('full-after-mango'), '1420')

    def test_ike_transition_states_also_get_bounded_grace(self):
        for phase in ['CREATED', 'PASSIVE', 'REKEYING', 'REKEYED', 'DELETING', 'DESTROYING']:
            with self.subTest(phase=phase):
                for p in self.state.iterdir():
                    if p.name != 'failover.lock': p.unlink()
                (self.r / 'trace').write_text('')
                self.d['now'] = 1000
                self.sas(f'mango: #1, {phase}, IKEv2\n')
                self.run_cycle(advance=False)
                self.assertEqual(self.value('transition-mango'), '1000 transition')
                self.assertFalse(any('--terminate' in r or '--initiate' in r for r in self.trace('swanctl')))
                self.d['now'] = 1120
                self.run_cycle(advance=False)
                self.assertTrue(any('--terminate' in r for r in self.trace('swanctl')))
                self.assertEqual(self.value('retry-after'), '1150')

    def test_stuck_connecting_cleanup_obeys_backoff(self):
        self.sas('mango: #1, CONNECTING, IKEv2\n')
        self.d['terminate_mode'] = 'stuck'
        self.run_cycle(advance=False)
        self.d['now'] = 1060
        self.run_cycle(advance=False)
        self.assertEqual(self.value('retry-after'), '1090')
        count = len([r for r in self.trace('swanctl') if '--terminate' in r])
        self.assertEqual(count, 2)
        self.d['now'] = 1089
        self.run_cycle(advance=False)
        self.assertEqual(len([r for r in self.trace('swanctl') if '--terminate' in r]), count)
        self.assertEqual(self.value('fail-count'), '1')
        self.d['now'] = 1090
        self.run_cycle(advance=False)
        self.assertEqual(len([r for r in self.trace('swanctl') if '--terminate' in r]), count + 2)

    def test_child_installed_during_timeout_recheck_is_not_terminated(self):
        self.sas(sa_rekeyed_only())
        (self.state / 'transition-mango').write_text('1 transition\n')
        self.d.update(sas_on_read=2, next_sas=sa())
        self.run_cycle(advance=False)
        self.assertFalse(any('--terminate' in r or '--initiate' in r for r in self.trace('swanctl')))
        self.assertFalse((self.state / 'transition-mango').exists())
        self.run_cycle()
        self.assertEqual(self.value('logged-up'), 'mango')

    def test_installed_child_wins_over_old_rekey_and_expired_timer(self):
        self.sas(sa() + '  mango: #9, reqid 1, REKEYED, TUNNEL\n')
        (self.state / 'transition-mango').write_text('1 transition\n')
        self.run_cycle()
        self.assertEqual(self.value('logged-up'), 'mango')
        self.assertFalse(any('--terminate' in row or '--initiate' in row
                             for row in self.trace('swanctl')))
        self.assertFalse((self.state / 'transition-mango').exists())

    def test_recovery_clears_transition_clock_for_next_episode(self):
        self.sas(sa_rekeyed_only())
        self.run_cycle(advance=False)
        self.sas(sa())
        self.d['now'] = 1050
        self.run_cycle()
        self.sas(sa_rekeyed_only())
        self.d['now'] = 1100
        self.run_cycle(advance=False)
        self.assertEqual(self.value('transition-mango'), '1100 transition')

    def test_post_child_transition_is_pending_not_connected_and_times_out(self):
        self.sas(sa(installed=False))
        self.d['init_transition'] = 'REKEYED'
        self.run_cycle(advance=False)
        self.assertEqual(self.value('transition-mango'), '1000 transition')
        self.assertFalse((self.state / 'logged-up').exists())
        self.assertFalse((self.state / 'fail-count').exists())
        self.d['now'] = 1120
        self.run_cycle(advance=False)
        self.assertTrue(any('--terminate' in row for row in self.trace('swanctl')))

    def test_full_initiate_detach_does_not_hide_stuck_connecting(self):
        self.d['init_transition'] = 'CONNECTING'
        self.run_cycle(advance=False)
        self.assertFalse((self.state / 'logged-up').exists())
        self.assertFalse((self.state / 'fail-count').exists())
        self.d['now'] = 1060
        self.run_cycle(advance=False)
        self.assertEqual(self.value('fail-count'), '1')
        self.assertTrue(any('--terminate' in row for row in self.trace('swanctl')))

    def test_post_initiate_query_failure_does_not_report_connected(self):
        self.d.update(dial_ok=True, list_fail_after_init=True)
        self.run_cycle()
        self.assertFalse((self.state / 'logged-up').exists())
        self.assertFalse((self.state / 'health-up').exists())
        prior = len([row for row in self.trace('swanctl') if '--initiate' in row])
        self.run_cycle()
        self.assertEqual(len([row for row in self.trace('swanctl') if '--initiate' in row]), prior)

    def test_apply_also_confirms_cleanup_before_clearing_vip(self):
        prepared = self.prepare_init()
        self.orphan()
        self.d['terminate_mode'] = 'stuck'
        self.assertNotEqual(self.run_init(prepared, 'reload').returncode, 0)
        self.assertFalse(any('flush' in row for row in self.trace('ip')))
        self.assertFalse(any('--initiate' in row for row in self.trace('swanctl')))

    def prepare_init(self):
        for name in ['mango-ikev2-fw', 'mango-ikev2-watch-start', 'mango-ikev2-dns-on',
                     'swanctl-service', 'nft']:
            (self.bin / name).symlink_to(self.mock)
        self.script.chmod(0o755)
        (self.bin / 'mango-ikev2-failover').symlink_to(self.script)
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
        script = '''extra_command() { :; }
. "$1"
mango_ikev2_watch_start() { mango-ikev2-watch-start; }
mango_ikev2_watch_stop() { :; }
mango_ikev2_claim_charon() { :; }
mango_ikev2_dns_on() { mango-ikev2-dns-on; }
mango_ikev2_dns_off() { :; }
"$2"
'''
        return init, script

    def run_init(self, prepared, action='start'):
        init, script = prepared
        (self.r / 'fixture.json').write_text(json.dumps(self.d))
        result = subprocess.run(['sh', '-c', script, 'sh', str(init), action],
                                env=self.env, timeout=10)
        self.d = json.loads((self.r / 'fixture.json').read_text())
        return result

    def test_boot_vici_not_ready_keeps_watch_and_installs_dns(self):
        prepared = self.prepare_init()
        self.d['load_rc'] = 1
        result = self.run_init(prepared)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.trace('mango-ikev2-watch-start'))
        self.assertTrue(self.trace('mango-ikev2-dns-on'))
        self.assertEqual(len([r for r in self.trace('swanctl') if '--load-all' in r]), 10)
        self.d.update(load_rc=0, dial_ok=True)
        self.run_cycle()
        self.assertEqual(self.value('logged-up'), 'mango')

    def test_start_reload_restart_reset_previous_300_second_backoff(self):
        prepared = self.prepare_init()
        for action in ['start', 'reload', 'restart']:
            with self.subTest(action=action):
                for name, value in [('active', 'mango3'), ('fail-count', '1'),
                                    ('fallback-fail', '12'), ('retry-after', '99999')]:
                    (self.state / name).write_text(value)
                tracking = ['probe-fail-mango', 'child-fail-mango', 'transition-mango',
                            'full-pending-mango', 'full-after-mango']
                for name in tracking:
                    (self.state / name).write_text('99999')
                self.assertEqual(self.run_init(prepared, action).returncode, 0)
                self.assertEqual(self.value('active'), 'mango')
                self.assertEqual(self.value('fail-count'), '1')
                self.assertEqual(self.value('fallback-fail'), '1')
                self.assertEqual(int(self.value('retry-after')) - self.d['now'], 30)
                for name in tracking:
                    self.assertFalse((self.state / name).exists(), name)

    def test_unready_wan_reload_resets_counts_before_delayed_watch_retry(self):
        prepared = self.prepare_init()
        (self.state / 'fallback-fail').write_text('12')
        (self.state / 'fail-count').write_text('1')
        (self.state / 'retry-after').write_text('99999')
        self.d['wan_up'] = False
        self.assertNotEqual(self.run_init(prepared, 'reload').returncode, 0)
        self.assertEqual(self.value('fallback-fail'), '0')
        self.assertEqual(self.value('fail-count'), '0')
        self.assertFalse((self.state / 'retry-after').exists())
        self.d['wan_up'] = True
        self.run_cycle(advance=False)
        self.assertEqual(self.value('fallback-fail'), '1')
        self.assertEqual(int(self.value('retry-after')) - self.d['now'], 30)

    def test_wan_reload_does_not_inherit_hotplug_lock(self):
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


class EventLog(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name) / 'events.log'
        self.script = PACKAGE / 'usr/libexec/mango-ikev2-log'
        self.env = dict(os.environ, MANGO_IKEV2_EVENT_LOG=str(self.log))

    def run_log(self, *args):
        return subprocess.run(['sh', str(self.script), *args], env=self.env,
                              text=True, capture_output=True)

    def test_rejects_unknown_and_blank_without_writing(self):
        for args in [(), ('nope', 'mango', 'x'), ('', 'mango', 'x')]:
            result = self.run_log(*args)
            self.assertEqual(result.returncode, 2, (args, result.stderr))
            self.assertFalse(self.log.exists(), args)

    def test_accepts_warn_and_existing_results(self):
        for name in ['ok', 'warn', 'fail', 'switch', 'backoff', 'down']:
            result = self.run_log(name, 'mango', 'detail ' + name)
            self.assertEqual(result.returncode, 0, result.stderr)
        rows = [line.split('\t') for line in self.log.read_text().splitlines()]
        self.assertEqual([row[1] for row in rows],
                         ['ok', 'warn', 'fail', 'switch', 'backoff', 'down'])
        self.assertTrue(all(row[2] == '主服务器' and row[5] == 'detail ' + row[1] for row in rows))
        self.assertEqual(len(rows), 6)

    def test_warn_accepted_by_busybox_ash(self):
        if not Path('/usr/bin/busybox').exists():
            self.skipTest('busybox ash is not installed')
        result = subprocess.run(['busybox', 'ash', str(self.script), 'warn', 'mango2',
                                 'tunnel probes failed (1/3)'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        unknown = subprocess.run(['busybox', 'ash', str(self.script), 'bogus'],
                                 env=self.env, text=True, capture_output=True)
        self.assertEqual(unknown.returncode, 2)
        row = self.log.read_text().splitlines()[-1].split('\t')
        self.assertEqual(row[1], 'warn')
        self.assertEqual(row[2], '备用服务器1')
        self.assertEqual(row[5], 'tunnel probes failed (1/3)')

    def test_luci_log_view_labels_warn(self):
        path = (ROOT / 'package/luci-app-mango-ikev2/htdocs/luci-static/resources/view/mango-ikev2/log.js')
        text = path.read_text()
        self.assertIn("warn: '警告'", text)
        self.assertIn("warn: 'warning'", text)
        self.assertNotIn("warn: 'danger'", text)
        self.assertNotIn("warn: '失败'", text)
        subprocess.run(['node', '--check', str(path)], check=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
