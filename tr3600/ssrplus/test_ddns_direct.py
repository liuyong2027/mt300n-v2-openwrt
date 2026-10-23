"""Test marked Dynu sockets against an isolated TLS WAN and SSR-like OUTPUT.

Linux native: python3 test_ddns_direct.py --framework PATH --report REPORT
Packed ARM64: python3 test_ddns_direct.py --root ROOTFS --report REPORT
Requires gcc, curl, openssl, iproute2, nftables, util-linux and passwordless sudo.
Packed mode requires --qemu pointing to the test-only SO_MARK-enabled QEMU
built by build-test-qemu.sh. No real provider is contacted.
"""
import argparse
import ctypes
import hashlib
import http.server
import importlib.util
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PACKAGE = HERE / 'cudy-ddns-direct'
DIRECT_IP = '1.2.3.1'
TARGET_IP = '1.2.3.2'
PROXY_IP = '185.0.0.1'
DEVICE = 'ddnswan'


def run(command, *, ok=True, **kwargs):
    result = subprocess.run([str(v) for v in command], capture_output=True,
                            text=True, timeout=20, **kwargs)
    if ok:
        assert result.returncode == 0, (command, result.returncode, result.stderr)
    return result


def wait_for(check, message):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.02)
    raise AssertionError(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location('cudy_ddns_patch', HERE / 'patch-ddns.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def function(text, name):
    import re
    match = re.search(r'^' + name + r'\s*\(\)\s*\{.*?^\}', text, re.M | re.S)
    assert match, 'Missing actual framework function ' + name
    return match.group(0)


def source_checks(framework, temporary, cases):
    """Patch the real framework, not a reimplementation; also test atomic drift rejection."""
    patcher = load_patcher()
    working = temporary / 'source'
    working.mkdir()
    f = working / 'functions.sh'
    r = working / 'resolver'
    f.write_text(framework.read_text())
    resolver = REPO / 'tr3600/network-root/usr/libexec/cudy-dynu-resolve'
    r.write_bytes(resolver.read_bytes())
    patcher.patch_paths(f, r)
    once = (f.read_bytes(), r.read_bytes())
    patcher.patch_paths(f, r)
    assert once == (f.read_bytes(), r.read_bytes())
    assert f.read_text().count(patcher.BLOCK) == 1
    assert '/usr/libexec/cudy-ddns-curl -4 --interface ' in r.read_text()
    cases.append('real framework and resolver patch is exact and idempotent')
    bad = working / 'bad-resolver'
    bad.write_text('upstream resolver changed\n')
    before = f.read_bytes()
    try:
        patcher.patch_paths(f, bad)
    except AssertionError:
        pass
    else:
        raise AssertionError('Changed resolver anchor accepted')
    assert f.read_bytes() == before
    badf = working / 'bad-framework'
    badf.write_text('upstream framework changed\n')
    before = r.read_bytes()
    try:
        patcher.patch_paths(badf, r)
    except AssertionError:
        pass
    else:
        raise AssertionError('Changed framework anchor accepted')
    assert r.read_bytes() == before
    cases.append('upstream drift rejected before either input is changed')
    run(['sh', '-n', str(f)])
    run(['sh', '-n', str(PACKAGE / 'files/cudy-ddns-curl')])
    run(['sh', '-n', str(PACKAGE / 'files/80-cudy-ddns-direct')])
    return f.read_text()


class Echo(http.server.BaseHTTPRequestHandler):
    proxy = False

    def do_GET(self):
        body = (PROXY_IP if self.proxy else self.client_address[0]) + '\n'
        data = body.encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


def tls_server(cert, key, port, proxy=False):
    handler = type('FixtureEcho', (Echo,), {'proxy': proxy})
    server = http.server.ThreadingHTTPServer(('0.0.0.0', port), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def counters():
    data = json.loads(run(['nft', '-j', 'list', 'table', 'inet', 'cudy_ddns_test']).stdout)
    found = {}
    for value in data['nftables']:
        rule = value.get('rule', {})
        if 'comment' in rule:
            for expression in rule.get('expr', []):
                if 'counter' in expression:
                    found[rule['comment']] = expression['counter']['packets']
    return found


def no_mark_permissions():
    # Do not rely on the runner's capabilities being absent after setuid.
    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(8, 0, 0, 0, 0) == 0  # PR_SET_KEEPCAPS=0
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)


def compile_native(temporary):
    compiler = shutil.which('gcc') or shutil.which('cc')
    assert compiler
    library = temporary / 'socket-mark.so'
    launcher = temporary / 'cudy-ddns-direct'
    common = [compiler, '-Wall', '-Wextra', '-Werror', '-O2']
    run(common + ['-fPIC', '-shared', '-o', library, PACKAGE / 'src/socket-mark.c', '-ldl'])
    constants = ['-DCUDY_DDNS_LIBRARY=' + json.dumps(str(library)),
                 '-DCUDY_DDNS_CURL="/usr/bin/curl"']
    run(common + constants + ['-o', launcher, PACKAGE / 'src/launcher.c', '-ldl'])
    return library, launcher


def framework_transfer(text, temporary, launcher, cert, service, *, current=False,
                       suffix='', bind=True):
    # Only the install prefix is adapted to the isolated native fixture.
    body = function(text, 'do_transfer').replace('/usr/libexec/cudy-ddns-curl', str(launcher))
    source = '''set -u
write_log() { [ "$1" -lt 10 ] || exit 90; }
network_get_device() { [ "$2" = wan ] && eval "$1=ddnswan"; }
'''
    values = dict(CURL='/usr/bin/curl --resolve fixture.invalid:443:1.2.3.2 --connect-timeout 1 --max-time 3' + suffix,
                  USE_CURL='1', CURL_SSL='https', CURL_PROXY='yes', WGET_SSL='',
                  bind_network='wan' if bind else '', use_ipv6='0', use_https='1',
                  force_ipversion='1', cacert=str(cert), proxy='', user_agent='',
                  DATFILE=str(temporary / 'framework.data'), ERRFILE=str(temporary / 'framework.err'),
                  LUCI_HELPER='1', VERBOSE='0', retry_max_count='0', RETRY_SECONDS='0',
                  service_name=service, ip_source='web', ip_url='https://fixture.invalid/',
                  IPV4_REGEX=r'[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}')
    source += '\n'.join(k + '=' + shlex.quote(v) for k, v in values.items()) + '\n'
    source += body + '\n'
    if current:
        source += function(text, 'get_current_ip') + '\nget_current_ip CURRENT_IP || exit 1\nprintf "%s\\n" "$CURRENT_IP"\n'
    else:
        source += 'do_transfer "$ip_url" || exit 1\ncat "$DATFILE"\n'
    source += '[ -z "${LD_PRELOAD:-}" ] || exit 91\n'
    script = temporary / 'framework-fixture.sh'
    script.write_text(source)
    return run(['sh', script], ok=False)


def provider_contract(temporary, cases):
    # Source the real provider with synthetic credentials and a no-network
    # do_transfer spy. The exact URL encoding and --resolve suffix must survive.
    provider = REPO / 'tr3600/network-root/usr/lib/ddns/update_cudy_dynu_https.sh'
    stub = temporary / 'resolver-stub'
    stub.write_text('#!/bin/sh\n[ "$1" = --public-ip ] || echo 1.2.3.2\n')
    stub.chmod(0o755)
    copy = temporary / 'provider.sh'
    copy.write_text(provider.read_text().replace('/usr/libexec/cudy-dynu-resolve', str(stub)))
    harness = r'''set -eu
write_log() { :; }
do_transfer() {
 [ "$CURL" = '/usr/bin/curl --resolve api.dynu.com:443:1.2.3.2 --connect-timeout 4 --max-time 10' ]
 [ "$1" = 'https://api.dynu.com/nic/update?hostname=fixture.example.net&myip=1.2.3.1&myipv6=no&username=fixture%40user&password=fixture%26only' ]
 printf 'good 1.2.3.1\n' > "$DATFILE"
}
CURL=/usr/bin/curl URL_USER=fixture%40user URL_PASS=fixture%26only domain=fixture.example.net
use_https=1 use_ipv6=0 __IP=1.2.3.1
DATFILE=@DATA@
invoke() { . @PROVIDER@; }
invoke
[ "$CURL" = /usr/bin/curl ]
[ -z "${LD_PRELOAD:-}" ]
'''.replace('@DATA@', shlex.quote(str(temporary / 'provider.data'))).replace('@PROVIDER@', shlex.quote(str(copy)))
    run(['sh', '-c', harness])
    cases.append('real provider retains encoded credentials and --resolve suffix without network requests')


def upgrade_fixtures(temporary, cases):
    source = (PACKAGE / 'files/80-cudy-ddns-direct').read_text()
    base = REPO / 'tr3600/network-root'
    legacy_resolver = (base / 'usr/libexec/cudy-dynu-resolve').read_text().encode()
    legacy_keep = (base / 'lib/upgrade/keep.d/cudy-dynu-ddns').read_text().encode()
    assert hashlib.sha256(legacy_resolver).hexdigest() in source
    assert hashlib.sha256(legacy_keep).hexdigest() in source
    new_resolver = legacy_resolver.replace(b'/usr/bin/curl -4 --interface ',
                                        b'/usr/libexec/cudy-ddns-curl -4 --interface ')
    new_keep = b'/etc/config/ddns\n'
    for name in ('known-legacy', 'already-new', 'owner-custom'):
        prefix = temporary / name
        prefix.mkdir()
        paths = {'resolver': prefix / 'resolver', 'rom_resolver': prefix / 'rom-resolver',
                 'keep': prefix / 'keep', 'rom_keep': prefix / 'rom-keep'}
        paths['rom_resolver'].write_bytes(new_resolver)
        paths['rom_keep'].write_bytes(new_keep)
        if name == 'known-legacy':
            old = (legacy_resolver, legacy_keep)
        elif name == 'already-new':
            old = (new_resolver, new_keep)
        else:
            old = (b'owner custom resolver\n', b'owner custom keep list\n')
        paths['resolver'].write_bytes(old[0])
        paths['keep'].write_bytes(old[1])
        owner_config = prefix / 'ddns-config'
        owner_config.write_bytes(b"config service 'synthetic'\n option password 'synthetic-only'\n")
        before_config = owner_config.read_bytes()
        before_mtime = [paths[k].stat().st_mtime_ns for k in ('resolver', 'keep')]
        fixture = source
        fixed = {'resolver': '/usr/libexec/cudy-dynu-resolve',
                 'rom_resolver': '/rom/usr/libexec/cudy-dynu-resolve',
                 'keep': '/lib/upgrade/keep.d/cudy-dynu-ddns',
                 'rom_keep': '/rom/lib/upgrade/keep.d/cudy-dynu-ddns'}
        for key, value in fixed.items():
            assignment = key + '=' + value
            assert fixture.count(assignment) == 1
            fixture = fixture.replace(assignment, key + '=' + shlex.quote(str(paths[key])))
        script = prefix / 'run.sh'
        script.write_text('logger() { printf "%s\\n" "$*"; }\n' + fixture)
        result = run(['sh', script])
        assert owner_config.read_bytes() == before_config
        if name == 'known-legacy':
            assert paths['resolver'].read_bytes() == new_resolver
            assert paths['keep'].read_bytes() == new_keep
            assert result.stdout.count('restored from the new firmware') == 2
        else:
            assert paths['resolver'].read_bytes() == old[0]
            assert paths['keep'].read_bytes() == old[1]
            assert [paths[k].stat().st_mtime_ns for k in ('resolver', 'keep')] == before_mtime
            if name == 'owner-custom':
                assert result.stdout.count('custom version; preserved for owner review') == 2
            else:
                assert result.stdout == ''
        # A repeated first-boot invocation is safe after either outcome.
        run(['sh', script])
        assert owner_config.read_bytes() == before_config
        cases.append('actual first-boot repair ' + name + ': config preserved; repeat safe')


def inside(args):
    assert os.geteuid() == 0
    assert os.readlink('/proc/self/ns/net') != os.readlink('/proc/1/ns/net'), 'private netns required'
    assert os.readlink('/proc/self/ns/mnt') != os.readlink('/proc/1/ns/mnt'), 'private mountns required'
    existing = json.loads(run(['nft', '-j', 'list', 'ruleset']).stdout)['nftables']
    assert all(set(item) == {'metainfo'} for item in existing), 'new empty netns required'
    run(['mount', '-t', 'sysfs', 'sysfs', '/sys'])
    run(['ip', 'link', 'set', 'lo', 'up'])
    cases = []
    with tempfile.TemporaryDirectory(prefix='cudy-ddns-direct-') as directory:
        temporary = Path(directory)
        temporary.chmod(0o755)
        framework = args.framework or (args.root / 'usr/lib/ddns/dynamic_dns_functions.sh' if args.root else
            REPO / 'openwrt/feeds/packages/net/ddns-scripts/files/usr/lib/ddns/dynamic_dns_functions.sh')
        assert framework.is_file(), '--framework must point to the actual pinned DDNS framework'
        text = source_checks(framework, temporary, cases)
        library, launcher = compile_native(temporary)
        provider_contract(temporary, cases)
        upgrade_fixtures(temporary, cases)
        cert, key = temporary / 'cert.pem', temporary / 'key.pem'
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-days', '1', '-nodes',
             '-subj', '/CN=fixture.invalid', '-addext', 'subjectAltName=DNS:fixture.invalid',
             '-keyout', key, '-out', cert])
        ready = temporary / 'peer-ready'
        peer = subprocess.Popen(['unshare', '--net', sys.executable, str(Path(__file__).resolve()),
            '--peer', '--cert', str(cert), '--key', str(key), '--ready', str(ready)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        proxy = None
        try:
            wait_for(lambda: ready.exists(), 'TLS peer did not start')
            assert peer.poll() is None
            run(['ip', 'link', 'add', DEVICE, 'type', 'veth', 'peer', 'name', 'ddnspeer'])
            run(['ip', 'link', 'set', 'ddnspeer', 'netns', str(peer.pid)])
            run(['ip', 'address', 'add', DIRECT_IP + '/24', 'dev', DEVICE])
            run(['ip', 'link', 'set', DEVICE, 'up'])
            for command in (['ip', 'link', 'set', 'lo', 'up'],
                            ['ip', 'address', 'add', TARGET_IP + '/24', 'dev', 'ddnspeer'],
                            ['ip', 'link', 'set', 'ddnspeer', 'up']):
                run(['nsenter', '-t', str(peer.pid), '-n'] + command)
            proxy = tls_server(cert, key, 18443, proxy=True)
            threading.Thread(target=proxy.serve_forever, daemon=True).start()
            run(['nft', '-f', '-'], input='''table inet cudy_ddns_test {
 chain output {
  type nat hook output priority 0; policy accept;
  meta nfproto ipv4 tcp dport 443 meta mark 255 counter return comment "marked-direct"
  meta nfproto ipv4 tcp dport 443 counter redirect to :18443 comment "transparent-proxy"
 }
}
''')
            # Match the production resolver's 4/8-second budgets. Packed curl
            # uses its SIGALRM resolver, which rejects a remaining deadline
            # below one whole second before attempting the synthetic request.
            options = ['-4', '--noproxy', '*', '--connect-timeout', '4', '--max-time', '8',
                       '--cacert', str(cert), '--resolve', 'fixture.invalid:443:' + TARGET_IP,
                       '-fsS', 'https://fixture.invalid/']
            unbound = run(['/usr/bin/curl'] + options).stdout.strip()
            assert unbound == PROXY_IP, unbound
            assert run(['/usr/bin/curl', '--interface', DEVICE] + options, ok=False).returncode != 0
            cases.append('actual bound curl reproduces transparent OUTPUT timeout; unbound reports proxy fixture')
            native_before = counters()['marked-direct']
            hostile = dict(os.environ, ALL_PROXY='http://127.0.0.1:9', all_proxy='http://127.0.0.1:9',
                           http_proxy='http://127.0.0.1:9', https_proxy='http://127.0.0.1:9',
                           CUDY_DDNS_MARK='0', CUDY_DDNS_DIRECT_MARK='4294967296junk')
            # No --noproxy in the call: the launcher itself must disable proxies.
            marked_options = [v for v in options]
            marked_options[1:3] = []
            response = run([launcher, '--interface', DEVICE] + marked_options, env=hostile)
            assert response.stdout.strip() == DIRECT_IP
            assert counters()['marked-direct'] > native_before
            cases.append('native launcher and shim preserve WAN/TLS, force full mark255, defeat environment proxy')
            assert framework_transfer(text, temporary, launcher, cert, 'cudy-dynu-https', current=True).stdout.strip() == DIRECT_IP
            assert framework_transfer(text, temporary, launcher, cert, 'cudy-dynu-https', suffix=' --resolve fixture.invalid:443:1.2.3.2').stdout.strip() == DIRECT_IP
            assert framework_transfer(text, temporary, launcher, cert, 'other-provider', bind=False).stdout.strip() == PROXY_IP
            cases.append('actual get_current_ip and provider-shaped do_transfer are marked; other provider unchanged')
            missing_ca = [v for v in marked_options]
            at = missing_ca.index('--cacert')
            del missing_ca[at:at + 2]
            assert run([launcher, '--interface', DEVICE] + missing_ca, ok=False).returncode != 0
            cases.append('untrusted TLS certificate still rejected')
            before = counters()
            failed = run([launcher, '--interface', DEVICE] + marked_options,
                         ok=False, preexec_fn=no_mark_permissions)
            assert failed.returncode == 125 and 'preflight failed' in failed.stderr
            assert counters() == before, 'unprivileged marking failure sent a request'
            moved = library.with_suffix('.absent')
            library.rename(moved)
            try:
                failed = run([launcher] + marked_options, ok=False)
                assert failed.returncode == 125 and counters() == before
            finally:
                moved.rename(library)
            cases.append('SO_MARK permission failure and missing shared object fail closed before any request')
            packed = None
            if args.root:
                root = args.root
                installed = root / 'usr/lib/cudy-ddns-direct/socket-mark.so'
                for path in (installed, root / 'usr/libexec/cudy-ddns-direct', root / 'usr/bin/curl'):
                    data = path.read_bytes()
                    assert data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == 183
                assert (root / 'usr/libexec/cudy-ddns-curl').read_bytes() == (PACKAGE / 'files/cudy-ddns-curl').read_bytes()
                assert (root / 'etc/uci-defaults/80-cudy-ddns-direct').read_bytes() == (PACKAGE / 'files/80-cudy-ddns-direct').read_bytes()
                assert (root / 'lib/upgrade/keep.d/cudy-dynu-ddns').read_text() == '/etc/config/ddns\n'
                assert '/usr/libexec/cudy-ddns-curl -4 --interface ' in (root / 'usr/libexec/cudy-dynu-resolve').read_text()
                assert load_patcher().BLOCK in (root / 'usr/lib/ddns/dynamic_dns_functions.sh').read_text()
                # UID 65534 must execute the emulator too, regardless of the
                # runner workspace's ancestor permissions. Copy only test code.
                emulator = temporary / 'qemu-aarch64'
                shutil.copyfile(shutil.which(args.qemu), emulator)
                emulator.chmod(0o755)
                run([emulator, '--version'], preexec_fn=no_mark_permissions)
                command = [str(emulator), '-L', str(root), '-E', 'LD_PRELOAD=' + str(installed), str(root / 'usr/bin/curl')]
                hostenv = dict(os.environ)
                hostenv.pop('LD_PRELOAD', None)
                before = counters()['marked-direct']
                response = run(command + ['--disable', '--interface', DEVICE] + options, env=hostenv)
                assert response.stdout.strip() == DIRECT_IP
                assert counters()['marked-direct'] > before
                before_failure = counters()
                read_probe = ('import sys\n'
                              'for path in sys.argv[1:]:\n'
                              ' with open(path,"rb") as stream:\n'
                              '  assert stream.read(4)==bytes([127,69,76,70])\n')
                run([sys.executable, '-c', read_probe, installed, root / 'usr/bin/curl'],
                    preexec_fn=no_mark_permissions)
                # Confirm the failure is real kernel SO_MARK permission denial,
                # not QEMU rejecting an unsupported syscall (ENOPROTOOPT).
                failed = run(command[:1] + ['-strace'] + command[1:] +
                             ['--disable', '--interface', DEVICE] + options,
                             env=hostenv, ok=False, preexec_fn=no_mark_permissions)
                assert failed.returncode != 0
                assert re.search(r'setsockopt\([^\n]*,1,36,[^\n]*\) = -1 errno=1 ', failed.stderr), failed.stderr
                assert counters() == before_failure, 'packed marking failure sent a request'
                cases.append('packed ARM64 curl plus installed ARM64 shim performs TLS over bound marked socket; no-cap failure stops')
                packed = {'runtime': 'actual packed ARM64 curl and socket-mark.so under QEMU',
                          'unprivileged_packed_files_readable': True,
                          'unprivileged_mark_errno': 'EPERM',
                          'emulator_version': run([emulator, '--version']).stdout.splitlines()[0],
                          'emulator_sha256': hashlib.sha256(emulator.read_bytes()).hexdigest(),
                          'shim_sha256': hashlib.sha256(installed.read_bytes()).hexdigest(),
                          'launcher': 'packed ELF/architecture checked; launcher behavior exercised by identical native source'}
            report = {'passed': True, 'cases': cases, 'case_count': len(cases),
                      'mark': 255, 'scope': 'fresh private network and mount namespaces; synthetic TLS WAN only',
                      'direct_source': DIRECT_IP, 'proxy_fixture_source': PROXY_IP,
                      'nft_counters': counters(), 'packed': packed,
                      'real_provider_requests': 0, 'production_configuration_changes': 0}
        finally:
            if proxy:
                proxy.shutdown()
                proxy.server_close()
            peer.terminate()
            try:
                peer.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                peer.kill()
                peer.communicate()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    args.report.chmod(0o644)
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=lambda v: Path(v).resolve())
    parser.add_argument('--framework', type=lambda v: Path(v).resolve())
    parser.add_argument('--report', type=lambda v: Path(v).resolve())
    parser.add_argument('--qemu', default='qemu-aarch64-static',
                        help='ARM64 user emulator with real SO_MARK syscall forwarding')
    parser.add_argument('--inside', action='store_true')
    parser.add_argument('--peer', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--cert', help=argparse.SUPPRESS)
    parser.add_argument('--key', help=argparse.SUPPRESS)
    parser.add_argument('--ready', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.peer:
        server = tls_server(args.cert, args.key, 443)
        Path(args.ready).touch()
        server.serve_forever()
    elif args.inside:
        assert args.report
        inside(args)
    else:
        assert sys.platform == 'linux', 'Real socket/nft test requires Linux'
        assert args.report
        command = ['unshare', '--net', '--mount', '--propagation', 'private', sys.executable,
                   str(Path(__file__).resolve()), '--inside', '--report', str(args.report),
                   '--qemu', args.qemu]
        if args.root:
            command += ['--root', str(args.root)]
        if args.framework:
            command += ['--framework', str(args.framework)]
        if os.geteuid() != 0:
            command = ['sudo', '-n'] + command
        subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
