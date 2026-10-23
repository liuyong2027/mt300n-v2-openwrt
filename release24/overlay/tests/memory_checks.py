"""Isolated recovery fixtures; never read or modify the host's router state."""
import fcntl
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import tempfile
import threading
import time

STUB = r'''#!/bin/sh
name=${0##*/}
case "$name" in
uci)
 case "$*" in
  '-q get mango_proxy.main.failover') [ "$SCENARIO" = disabled ] && echo 0 || echo 1;;
  '-q get mango_proxy.main.mode') [ "$SCENARIO" = direct ] && echo direct || echo split;;
  '-q export mango_proxy')
   if [ -f "$TESTROOT/configchange" ]; then echo config-B; else echo config-A; fi;;
  *) exit 1;;
 esac;;
mango-runtime-id)
 [ -f "$TESTROOT/identitychange" ] && echo runtime-B || echo runtime-A;;
mango-process)
 case "$1" in
 snapshot)
  [ -f "$TESTROOT/absent" ] && exit 0
  [ "$SCENARIO" = multiple ] && { echo '777:100 778:100'; exit 0; }
  [ "$SCENARIO" = missing ] && exit 0
  [ "$SCENARIO" = young ] && { echo 777:399500; exit 0; }
  echo 777:100;;
 cleanup)
  echo stop >> "$TESTROOT/actions"
  [ "$SCENARIO" = cleanupfail ] && exit 1
  : > "$TESTROOT/absent"
  [ "$SCENARIO" != config_after_stop ] || : > "$TESTROOT/configchange"
  exit 0;;
 absent) [ "$SCENARIO" != absentfail ] && [ -f "$TESTROOT/absent" ];;
 esac;;
mango-uplink) [ "$SCENARIO" = unknown ] && exit 2; [ "$SCENARIO" != offline ];;
mango-core-health)
 n=$(cat "$TESTROOT/checks" 2>/dev/null); n=${n:-0}; n=$((n+1)); echo "$n" > "$TESTROOT/checks"
 [ "$SCENARIO" != configchange ] || : > "$TESTROOT/configchange"
 [ "$SCENARIO" != identitychange ] || : > "$TESTROOT/identitychange"
 [ "$SCENARIO" != memory_recovers ] || echo 'MemAvailable: 32768 kB' > "$TESTROOT/meminfo"
 [ "$SCENARIO" != invalidcheck ] || exit 2
 [ "$SCENARIO" != healthy ] || exit 0
 [ "$SCENARIO" != transient ] || { [ "$n" -ge 2 ]; exit $?; }
 [ "$n" -ge 3 ];;
mango-probe) [ "$SCENARIO" != internetfail ];;
mango_proxy)
 [ "$1" = start ] || exit 90
 [ -f "$TESTROOT/absent" ] || { echo OVERLAP >> "$TESTROOT/actions"; exit 91; }
 echo start >> "$TESTROOT/actions"
 [ "$SCENARIO" != startfail ] || exit 1
 rm -f "$TESTROOT/absent";;
logger|sleep) exit 0;;
*) exit 93;;
esac
'''


def executable(path, body):
    path.write_text(body)
    path.chmod(0o755)


def guard_cases(source, shell):
    results = []
    cases = {
        'normal': (0, ''), 'healthy': (0, ''), 'transient': (0, ''),
        'hung': (20, 'stop\nstart'), 'offline': (10, ''), 'direct': (0, ''),
        'disabled': (0, ''), 'young': (10, ''), 'multiple': (10, ''), 'missing': (10, ''),
        'configchange': (10, ''), 'identitychange': (10, ''), 'memory_recovers': (10, ''),
        'invalidcheck': (10, ''), 'cooldown': (10, ''), 'budget': (10, ''),
        'cleanupfail': (20, 'stop'), 'config_after_stop': (20, 'stop'),
        'absentfail': (20, 'stop'), 'startfail': (20, 'stop\nstart'),
        'internetfail': (20, 'stop\nstart'), 'unknown': (20, 'stop\nstart'),
    }
    with tempfile.TemporaryDirectory(prefix='mango-memory-ci-') as directory:
        root = Path(directory); (root/'bin').mkdir(); (root/'state').mkdir()
        for name in ['uci', 'mango-runtime-id', 'mango-process', 'mango-uplink',
                     'mango-core-health', 'mango-probe', 'mango_proxy', 'logger', 'sleep']:
            executable(root/'bin'/name, STUB)
        body = (source/'usr/libexec/mango-memory-guard').read_text()
        mapping = {'/proc/meminfo': root/'meminfo', '/proc/uptime': root/'uptime',
                   '/var/lock/mango-operation.lock': root/'operation.lock',
                   '/var/etc/mango': root/'state', '/etc/init.d/mango_proxy': root/'bin/mango_proxy'}
        for name in ['mango-runtime-id', 'mango-process', 'mango-uplink', 'mango-core-health', 'mango-probe']:
            mapping['/usr/libexec/'+name] = root/'bin'/name
        for old, new in mapping.items(): body = body.replace(old, str(new))
        executable(root/'guard', body)
        env = dict(os.environ, PATH=str(root/'bin')+':'+os.environ['PATH'], TESTROOT=str(root))
        for name, (expected, actions) in cases.items():
            for stale in ['actions', 'checks', 'absent', 'identitychange', 'configchange', 'state/memory-guard-attempts']:
                (root/stale).unlink(missing_ok=True)
            (root/'uptime').write_text('4000.00 0.00\n')
            (root/'meminfo').write_text('MemAvailable: '+('32768' if name == 'normal' else '4096')+' kB\n')
            if name == 'cooldown': (root/'state/memory-guard-attempts').write_text('3950\n')
            if name == 'budget': (root/'state/memory-guard-attempts').write_text('800\n1800\n2800\n')
            result = subprocess.run(shell+[str(root/'guard')], env=dict(env, SCENARIO=name), capture_output=True, text=True, timeout=20)
            actual = (root/'actions').read_text().strip() if (root/'actions').exists() else ''
            assert (result.returncode, actual) == (expected, actions), (name, result.returncode, actual, result.stderr)
            if actions:
                attempts = (root/'state/memory-guard-attempts').read_text().splitlines()
                assert attempts == ['4000'], (name, attempts)
            results.append({'case': name, 'exit': expected, 'actions': actions.splitlines(), 'passed': True})
        # The sentinel alone must never bypass a real conflicting operation lock.
        with (root/'operation.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
            (root/'actions').unlink(missing_ok=True)
            for sentinel in ['0', '1']:
                result = subprocess.run(shell+[str(root/'guard')], env=dict(env, SCENARIO='hung', MANGO_OPERATION_LOCK=sentinel), capture_output=True, timeout=10)
                assert result.returncode == 10 and not (root/'actions').exists(), (sentinel, result.stderr)
                results.append({'case': 'real_lock_busy_sentinel_'+sentinel, 'passed': True})
    return results


def protocol_cases(source, shell, nc_command=None):
    results = []
    with tempfile.TemporaryDirectory(prefix='mango-protocol-ci-') as directory:
        root = Path(directory); (root/'bin').mkdir()
        if nc_command:
            executable(root/'bin/nc', '#!/bin/sh\nexec '+shlex.join(nc_command)+' "$@"\n')
        env = dict(os.environ, PATH=str(root/'bin')+':'+os.environ['PATH'], TMPDIR=str(root))
        for name, expected in [('healthy', 0), ('fragmented', 0), ('wrong', 1), ('stall', 1)]:
            with socket.socket() as server:
                server.bind(('127.0.0.1', 0)); server.listen(); server.settimeout(6)
                port = server.getsockname()[1]; received = []
                def serve():
                    with server.accept()[0] as connection:
                        connection.settimeout(4)
                        request = b''
                        while len(request) < 3:
                            chunk = connection.recv(3-len(request))
                            if not chunk: break
                            request += chunk
                        received.append(request)
                        if name == 'healthy': connection.sendall(b'\x05\x00')
                        elif name == 'fragmented':
                            connection.sendall(b'\x05'); time.sleep(.2); connection.sendall(b'\x00')
                        elif name == 'wrong': connection.sendall(b'\x05\xff')
                        time.sleep(3.2)
                thread = threading.Thread(target=serve, daemon=True); thread.start()
                body = (source/'usr/libexec/mango-core-health').read_text().replace('127.0.0.1 10808', '127.0.0.1 '+str(port)).replace('/tmp/mango-core-health.', str(root/'mango-core-health.'))
                executable(root/'health', body)
                start = time.monotonic()
                result = subprocess.run(shell+[str(root/'health')], env=env, capture_output=True, timeout=8)
                elapsed = time.monotonic()-start
                thread.join(5)
                assert result.returncode == expected and elapsed < 7, (name, result.returncode, result.stderr, elapsed)
                assert received == [b'\x05\x01\x00'], (name, received)
                assert not list(root.glob('mango-core-health.*')), 'Probe temporary directory leaked'
                results.append({'case': 'protocol_'+name, 'passed': True, 'seconds': round(elapsed, 3)})
    return results


def dns_cases(source, shell):
    results = []
    with tempfile.TemporaryDirectory(prefix='mango-dns-ci-') as directory:
        root=Path(directory); (root/'bin').mkdir()
        executable(root/'bin/uci', r'''#!/bin/sh
case "$*" in
 '-q get dhcp.@dnsmasq[0]') [ ! -e "$TESTROOT/missing" ] && echo dnsmasq;;
 '-q get dhcp.@dnsmasq[0].extraconftext') cat "$TESTROOT/extra";;
 'set dhcp.@dnsmasq[0].extraconftext='*) printf '%s' "${2#*=}" > "$TESTROOT/extra";;
 'commit dhcp') echo commit >> "$TESTROOT/commits";;
 *) exit 97;;
esac
''')
        (root/'board').write_text('glinet,gl-mt300n-v2\n')
        executable(root/'defaults', (source/'etc/uci-defaults/98-mango-memory').read_text().replace('/tmp/sysinfo/board_name', str(root/'board')))
        env=dict(os.environ, PATH=str(root/'bin')+':'+os.environ['PATH'], TESTROOT=str(root))
        for name, before, after in [
            ('fresh', '', 'max-tcp-connections=8'),
            ('other_options', 'cache-size=400\n# owner comment', 'cache-size=400\n# owner comment\nmax-tcp-connections=8'),
            ('custom', 'max-tcp-connections=12\ncache-size=400', 'max-tcp-connections=12\ncache-size=400'),
            ('custom_spaces', '  max-tcp-connections = 4', '  max-tcp-connections = 4'),
            ('already_eight', 'max-tcp-connections=8', 'max-tcp-connections=8'),
            ('comment_only', '# max-tcp-connections=12', '# max-tcp-connections=12\nmax-tcp-connections=8')]:
            (root/'extra').write_text(before); (root/'commits').unlink(missing_ok=True)
            for _ in range(2): subprocess.run(shell+[str(root/'defaults')], env=env, check=True, timeout=10)
            assert (root/'extra').read_text() == after, name
            commits=(root/'commits').read_text().splitlines() if (root/'commits').exists() else []
            assert len(commits) == int(before != after), (name, commits)
            results.append({'case': 'dns_'+name+'_idempotent', 'passed': True})
        for name in ['missing', 'other_board']:
            (root/'extra').write_text('owner=1'); (root/'commits').unlink(missing_ok=True)
            if name == 'missing': (root/'missing').touch()
            else: (root/'missing').unlink(); (root/'board').write_text('different-board\n')
            subprocess.run(shell+[str(root/'defaults')], env=env, check=True, timeout=10)
            assert (root/'extra').read_text() == 'owner=1' and not (root/'commits').exists(), name
            results.append({'case': 'dns_skip_'+name, 'passed': True})
    return results
