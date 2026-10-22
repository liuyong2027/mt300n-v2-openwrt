"""Encrypted SS acceptance tests; packed mode only changes a fresh network namespace.

--root runs the installed ARM64 Lua/libuci generators and Xray under QEMU.
--xray-command is a local preflight using the same Lua model through lupa;
it deliberately does not claim firewall, namespace or packed-image coverage.
"""
import argparse
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
PASSWORD = 'synthetic-ss-handshake-password-only-123456'
SS_PORT = 18388
SOCKS_PORT = 18080
ECHO_PORT = 19001
PROXY_PORT = 19002
TIMEOUT = 1.5


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def receive(sock, length):
    data = b''
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise EOFError('connection closed before the encrypted echo completed')
        data += chunk
    return data


def send_frame(sock,payload):
    sock.sendall(struct.pack('!I',len(payload))+payload)


def address(sock, atyp):
    if atyp == 1:
        host = socket.inet_ntop(socket.AF_INET, receive(sock, 4))
    elif atyp == 4:
        host = socket.inet_ntop(socket.AF_INET6, receive(sock, 16))
    elif atyp == 3:
        host = receive(sock, receive(sock, 1)[0]).decode('ascii')
    else:
        raise ValueError('unexpected SOCKS address type')
    return host, struct.unpack('!H', receive(sock, 2))[0]


def socks_command(command, target='0.0.0.0', port=0):
    sock = socket.create_connection(('127.0.0.1', SOCKS_PORT), TIMEOUT)
    sock.settimeout(TIMEOUT)
    try:
        sock.sendall(b'\x05\x01\x00')
        if receive(sock, 2) != b'\x05\x00':
            raise ValueError('SOCKS client refused no-auth negotiation')
        sock.sendall(bytes([5, command, 0, 1]) + socket.inet_aton(target) + struct.pack('!H', port))
        header = receive(sock, 4)
        if header[:3] != b'\x05\x00\x00':
            raise OSError('SOCKS request was rejected: ' + header.hex())
        relay = address(sock, header[3])
        return sock, relay
    except BaseException:
        sock.close()
        raise


def probe(protocol, target, payload, expected, echo_port=ECHO_PORT):
    if protocol == 'tcp':
        control, _ = socks_command(1, target, echo_port)
        with control:
            send_frame(control,payload)
            result = receive(control, len(expected))
    else:
        control, relay = socks_command(3)
        with control, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram:
            datagram.settimeout(TIMEOUT)
            host, port = relay
            if host in ('0.0.0.0', '::'):
                host = '127.0.0.1'
            datagram.connect((host, port))
            datagram.send(b'\x00\x00\x00\x01' + socket.inet_aton(target) + struct.pack('!H', echo_port) + payload)
            packet = datagram.recv(65535)
            if packet[:3] != b'\x00\x00\x00':
                raise ValueError('fragmented or invalid SOCKS UDP response')
            atyp = packet[3]
            offset = {1: 8, 4: 20}.get(atyp)
            if atyp == 3:
                offset = 5 + packet[4]
            if offset is None:
                raise ValueError('invalid SOCKS UDP response address')
            result = packet[offset + 2:]
    if result != expected:
        raise AssertionError('encrypted echo payload differs')
    return result


def echo(port, prefix, host):
    prefix = prefix.encode()
    def udp():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((host, port))
            while True:
                data, peer = sock.recvfrom(65535)
                sock.sendto(prefix + data, peer)
    threading.Thread(target=udp, daemon=True).start()
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen()
        while True:
            peer, _ = sock.accept()
            def respond(connection):
                with connection:
                    while True:
                        try:
                            length=struct.unpack('!I',receive(connection,4))[0]
                            if length>65535:
                                return
                            data=receive(connection,length)
                        except (EOFError,OSError):
                            return
                        connection.sendall(prefix + data)
            threading.Thread(target=respond, args=(peer,), daemon=True).start()


def verify_echo(target):
    for protocol in ('tcp','udp'):
        deadline=time.monotonic()+5
        while True:
            try:
                with socket.socket(socket.AF_INET,socket.SOCK_STREAM if protocol=='tcp' else socket.SOCK_DGRAM) as sock:
                    sock.settimeout(.3);sock.connect((target,ECHO_PORT))
                    payload=b'ECHO-FIXTURE-CONTROL';expected=b'DIRECT|'+payload
                    if protocol=='tcp':
                        send_frame(sock,payload)
                        result=receive(sock,len(expected))
                    else:
                        sock.sendall(payload);result=sock.recv(1024)
                    assert result==expected
                break
            except OSError:
                assert time.monotonic()<deadline,'TCP/UDP echo fixture is unavailable: '+protocol
                time.sleep(.05)


def password(method):
    if method.startswith('2022-'):
        size = 16 if method == '2022-blake3-aes-128-gcm' else 32
        return base64.b64encode(bytes(range(size))).decode()
    return PASSWORD


def row(method='aes-256-gcm', network='tcp,udp', scope='loopback'):
    return {'.name': 'fixture', 'type': 'shadowsocks', 'enable': '1',
        'server_port': str(SS_PORT), 'ss_method': method, 'ss_password': password(method),
        'ss_network': network, 'cudy_access': scope}


def client_config(raw, destination, source=None, secret=None):
    outbound = {'protocol': 'shadowsocks', 'settings': {'servers': [{
        'address': destination, 'port': SS_PORT, 'method': raw['ss_method'],
        'password': secret if secret is not None else raw['ss_password']} ]}}
    if source:
        outbound['sendThrough'] = source
    return {'log': {'loglevel': 'warning'}, 'inbounds': [{'listen': '127.0.0.1',
        'port': SOCKS_PORT, 'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': True}}],
        'outbounds': [outbound]}


class Programs:
    def __init__(self, command, directory):
        self.command, self.directory, self.serial = command, directory, 0
        self.children = []

    @contextmanager
    def process(self, command, namespace=None):
        self.serial += 1
        log = self.directory / ('process-%03d.log' % self.serial)
        if namespace:
            command = ['ip', 'netns', 'exec', namespace] + command
        with log.open('w') as output:
            child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            self.children.append(child)
            try:
                yield child
                assert child.poll() is None, log.read_text(errors='replace')
            except BaseException:
                output.flush()
                print('Process log: '+str(log)+'\n'+log.read_text(errors='replace')[-6000:],file=sys.stderr)
                raise
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait(timeout=5)
                self.children.remove(child)

    @contextmanager
    def core(self, config, namespace=None):
        self.serial += 1
        path = self.directory / ('core-%03d.json' % self.serial)
        path.write_text(json.dumps(config))
        run(*self.command, 'run', '-test', '-config', str(path),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with self.process(self.command + ['run', '-config', str(path)], namespace) as child:
            yield child


class NativeModel:
    def __init__(self, command=None, directory=None):
        from lupa.lua51 import LuaRuntime
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.model = self.lua.execute((HERE/'root/usr/lib/lua/cudy/ssr-server.lua').read_text())
        self.methods = [self.model.methods[i] for i in range(1, len(self.model.methods) + 1)]
        self.command,self.directory,self.parse_checks=command,directory,0

    def config(self, raw):
        def convert(value):
            if hasattr(value, 'items'):
                keys = list(value.keys())
                if keys and all(isinstance(key, int) for key in keys):
                    return [convert(value[i]) for i in range(1, len(value) + 1)]
                return {key: convert(item) for key, item in value.items()}
            return value
        config=convert(self.model.config(self.lua.table_from(raw)))
        if self.command:
            self.parse_checks+=1
            path=self.directory/('unmodified-production-%03d.json'%self.parse_checks)
            path.write_text(json.dumps(config))
            run(*self.command,'run','-test','-config',str(path),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        # Native preflight has no isolated routable interface. New Xray blocks
        # private destinations by default for SS inbounds, so permit only this
        # local echo target. Packed mode uses an isolated synthetic public route
        # and keeps the installed generated JSON completely unchanged.
        config['outbounds'][0]['settings']['finalRules']=[{'action':'allow','ip':['127.0.0.1/32']}]
        return config


class PackedModel:
    def __init__(self, root, directory):
        self.root, self.directory = root, directory
        self.command = ['qemu-aarch64-static', '-L', str(root), str(root/'usr/bin/lua')]
        self.environment = os.environ.copy()
        self.environment.update(LUA_PATH=str(root/'usr/lib/lua/?.lua')+';'+str(root/'usr/lib/lua/?/init.lua'),
            LUA_CPATH=str(root/'usr/lib/lua/?.so'))
        self.conf = directory/'config'; self.saved = directory/'saved'
        self.conf.mkdir(); self.saved.mkdir()
        driver = directory/'generator.lua'
        driver.write_text('''local root,conf,saved,action=arg[1],arg[2],arg[3],arg[4]
local native=require('uci');local original=native.cursor
native.cursor=function() return assert(original(conf,saved)) end
local json=require('luci.jsonc')
local real_dofile=dofile
dofile=function(path)
 if path:sub(1,17)=='/usr/lib/cudy-ss/' then path=root..path end
 return real_dofile(path)
end
local model=require('cudy.ssr-server')
if action=='methods' then print(json.stringify(model.methods));return end
local u=native.cursor()
if action=='config' then
 arg={'fixture'};dofile(root..'/usr/share/shadowsocksr/gen_cudy_ss_server.lua')
elseif action=='rules' or action=='closed-rules' then
 local rows={};u:foreach('shadowsocksr','server_config',function(s) rows[#rows+1]=s end)
 local active=action=='closed-rules' and {} or nil
 io.write(model.rules(rows,{device='lanfixture',addresses={'10.99.0.1'}},active))
else
 local n=dofile('/usr/lib/cudy-ss/config.lua')
 local v=dofile('/usr/lib/cudy-ss/ss-zt.lua')
 local c=n.validate(n.raw(u),v.validate)
 if action=='private-config' then print(json.stringify(n.config(assert(c))))
 elseif action=='private-rules' then io.write(n.guard(c))
 else error('Unknown test action') end
end
''')
        self.driver = driver
        self.methods = json.loads(self.lua('methods'))

    def lua(self, action):
        return subprocess.check_output(self.command + [str(self.driver), str(self.root),
            str(self.conf), str(self.saved), action], env=self.environment, text=True)

    def fixture(self, raw, enabled='1'):
        def quote(value):
            assert "'" not in str(value) and '\n' not in str(value)
            return "'"+str(value)+"'"
        lines=["config server_global 'server_global'", " option enable_server "+quote(enabled),
            "config server_config "+quote(raw['.name'])]
        lines += [' option '+key+' '+quote(value) for key,value in raw.items() if not key.startswith('.')]
        (self.conf/'shadowsocksr').write_text('\n'.join(lines)+'\n')

    def config(self, raw):
        self.fixture(raw)
        return json.loads(self.lua('config'))

    def rules(self, raw, active=True):
        self.fixture(raw)
        run('nft', '-f', '-', input=self.lua('rules' if active else 'closed-rules'))

    def private(self, raw, action, enabled='1'):
        self.fixture(raw, enabled)
        result = self.lua('private-'+action)
        if action == 'config':
            return json.loads(result)
        run('nft', '-f', '-', input=result)


class Acceptance:
    def __init__(self, model, programs, target, packed=False):
        self.model, self.programs, self.target, self.packed = model, programs, target, packed
        self.passed=[]

    def request(self, protocol, expected_prefix=b'DIRECT|', namespace=None, allowed=True):
        payload=b'SSRPLUS-ENCRYPTED-ECHO|'+os.urandom(256)
        data={'protocol':protocol,'target':self.target,'payload':base64.b64encode(payload).decode(),
            'expected':base64.b64encode(expected_prefix+payload).decode()}
        if namespace:
            result=subprocess.run(['ip','netns','exec',namespace,sys.executable,str(__file__),
                '--query',json.dumps(data)],capture_output=True,text=True)
            success=result.returncode==0
            failure=result.stderr
            assert result.returncode in (0,1),failure
        else:
            try:
                probe(protocol,self.target,payload,expected_prefix+payload)
                success=True;failure=''
            except (OSError,EOFError) as error:
                success=False;failure=str(error)
        assert success == allowed, (protocol,'expected allowed='+str(allowed),failure)

    def checks(self, label, namespace=None, allowed=True, prefix=b'DIRECT|'):
        for protocol in ('tcp','udp'):
            self.request(protocol,prefix,namespace,allowed)
            self.passed.append(label+'/'+protocol)

    def ready(self, namespace=None, protocol='tcp'):
        deadline=time.monotonic()+8
        while True:
            try:
                self.request(protocol,namespace=namespace)
                return
            except AssertionError:
                if time.monotonic()>=deadline:
                    raise
                time.sleep(.1)

    @contextmanager
    def client(self, raw, destination, namespace=None, source=None, secret=None):
        with self.programs.core(client_config(raw,destination,source,secret),namespace):
            # Wait for the local SOCKS listener, including UDP-only test cases.
            deadline=time.monotonic()+8
            while True:
                if namespace:
                    result=subprocess.run(['ip','netns','exec',namespace,sys.executable,'-c',
                        'import socket;s=socket.create_connection(("127.0.0.1",'+str(SOCKS_PORT)+'),.2);s.close()'],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    ready=result.returncode==0
                else:
                    try:
                        socket.create_connection(('127.0.0.1',SOCKS_PORT),.2).close();ready=True
                    except OSError:
                        ready=False
                if ready:break
                assert time.monotonic()<deadline,'Xray SOCKS listener did not start'
                time.sleep(.05)
            yield

    def matrix(self):
        for method in self.model.methods:
            raw=row(method)
            config=self.model.config(raw)
            if self.packed:self.model.rules(raw)
            with self.programs.core(config),self.client(raw,'127.0.0.1'):
                self.ready()
                self.checks('cipher/'+method)
        raw=row()
        for selected,denied in [('tcp','udp'),('udp','tcp')]:
            raw=row(network=selected)
            config=self.model.config(raw)
            if self.packed:self.model.rules(raw)
            with self.programs.core(config),self.client(raw,'127.0.0.1'):
                self.ready(protocol=selected)
                before=drop_count() if self.packed else 0
                self.request(denied,allowed=False)
                if self.packed:assert drop_count()>before,'Unselected transport did not hit the production drop rule'
                self.passed.extend(['transport/'+selected+'/allowed','transport/'+denied+'/denied'])
        raw=row()
        config=self.model.config(raw)
        if self.packed:self.model.rules(raw)
        with self.programs.core(config):
            with self.client(raw,'127.0.0.1'):
                self.ready();self.checks('password/correct')
            with self.client(raw,'127.0.0.1',secret='intentionally-wrong-synthetic-password'):
                self.checks('password/wrong',allowed=False)
            with self.client(raw,'127.0.0.1'):
                self.checks('password/correct-after-negative')


def drop_count():
    rules=json.loads(subprocess.check_output(['nft','-j','list','ruleset'],text=True))
    count=0
    for entry in rules['nftables']:
        expressions=entry.get('rule',{}).get('expr',[])
        if any('drop' in expression for expression in expressions):
            count+=sum(expression.get('counter',{}).get('packets',0) for expression in expressions)
    return count


class Network:
    def __init__(self):
        self.created=[]
        self.names={name:'ssr-ss-'+name+'-'+str(os.getpid()) for name in ('lan','wan','zt')}

    def pair(self, name, device, rootip, peerip):
        namespace=self.names[name]
        run('ip','netns','add',namespace);self.created.append(namespace)
        peer='ss-peer-'+name
        run('ip','link','add',device,'type','veth','peer','name',peer)
        run('ip','link','set',peer,'netns',namespace)
        run('ip','address','add',rootip+'/24','dev',device)
        run('ip','link','set',device,'up')
        run('ip','-n',namespace,'link','set','lo','up')
        run('ip','-n',namespace,'address','add',peerip+'/24','dev',peer)
        run('ip','-n',namespace,'link','set',peer,'up')
        run('ip','-n',namespace,'route','add','default','via',rootip)

    def setup(self):
        assert os.geteuid()==0,'Packed network acceptance requires root inside unshare'
        run('ip','link','set','lo','up')
        run('sysctl','-w','net.ipv4.ip_forward=1',stdout=subprocess.DEVNULL)
        self.pair('lan','lanfixture','10.99.0.1','10.99.0.2')
        self.pair('wan','wanfixture','1.2.3.1','1.2.3.2')
        self.pair('zt','ztabcdef','10.42.0.2','10.42.0.3')
        run('ip','-n',self.names['zt'],'address','add','10.42.1.3/24','dev','ss-peer-zt')
        run('ip','route','add','10.42.1.0/24','dev','ztabcdef')
        run('nft','-f','-',input='''table inet fw4 {
chain CUDY_SSR_SERVER {}
chain input { type filter hook input priority 0; policy drop;
iifname "lo" accept
ct state established,related accept
iifname "css-host" meta l4proto { tcp, udp } th dport 19002 accept
jump CUDY_SSR_SERVER
}
}
''')

    def close(self):
        for namespace in reversed(self.created):
            run('ip','netns','del',namespace)


def scopes(test, network):
    for scope in ('loopback','lan','public'):
        raw=row(scope=scope)
        config=test.model.config(raw);test.model.rules(raw)
        with test.programs.core(config):
            destination='127.0.0.1' if scope=='loopback' else '10.99.0.1'
            ns=None if scope=='loopback' else network.names['lan']
            with test.client(raw,destination,ns):
                test.ready(ns);test.checks('scope/'+scope+'/authorized',ns)
            for source,destination in [('wan','1.2.3.1'),('zt','10.42.0.2')]:
                ns=network.names[source]
                allowed=scope=='public'
                with test.client(raw,destination,ns):
                    before=drop_count()
                    test.checks('scope/'+scope+'/'+source,ns,allowed)
                    if not allowed:assert drop_count()>before,'Forbidden scope missed the production drop rule'
            if scope=='lan':
                with test.client(raw,'10.42.0.2',network.names['lan']):
                    before=drop_count()
                    test.checks('scope/lan/wrong-destination',network.names['lan'],False)
                    assert drop_count()>before,'LAN accept was not restricted to the LAN IPv4 endpoint'
    raw=row()
    config=test.model.config(raw);test.model.rules(raw)
    with test.programs.core(config),test.client(raw,'127.0.0.1'):
        test.ready()
        test.model.rules(raw,active=False)
        before=drop_count()
        test.checks('scope/configured-but-not-started',allowed=False)
        assert drop_count()>before,'An inactive configured server retained its accept rule'
        test.model.rules(raw)
        test.checks('scope/active-again')


def private_namespace(test, network, root, directory):
    existing=subprocess.check_output(['ip','netns','list'],text=True)
    assert not any(line.split()[0]=='cudy-ss' for line in existing.splitlines()),'Refusing an existing private namespace'
    helper=(root/'usr/libexec/cudy-ss-netns').read_text()
    helper=helper.replace('dir=/var/run/cudy-ss','dir='+str(directory/'private-run'))
    helper=helper.replace('/var/lock/cudy-ss-netns.lock',str(directory/'private.lock'))
    helper=helper.replace('lua /usr/lib/cudy-ss/check-prefix.lua','lua5.1 '+str(root/'usr/lib/cudy-ss/check-prefix.lua'))
    script=directory/'private-netns';script.write_text(helper)
    run('sh',str(script),'start')
    network.created.append('cudy-ss')
    try:
        raw=row();raw.update({'.name':'cudy_zt_private','cudy_private':'1','cudy_access':'zerotier',
            'cudy_zt_network_id':'0123456789abcdef','cudy_zt_interface':'ztabcdef',
            'cudy_zt_listen':'10.42.0.2','cudy_zt_subnet':'10.42.0.0/24'})
        for method in ('aes-128-gcm','aes-256-gcm','chacha20-ietf-poly1305'):
            candidate=dict(raw,ss_method=method)
            test.model.private(candidate,'rules')
            config=test.model.private(candidate,'config')
            with test.programs.core(config,'cudy-ss'),test.client(candidate,'10.42.0.2',network.names['zt']):
                test.ready(network.names['zt'])
                test.checks('private/cipher/'+method,network.names['zt'])
        for selected,denied in [('tcp','udp'),('udp','tcp')]:
            candidate=dict(raw,ss_network=selected)
            test.model.private(candidate,'rules')
            config=test.model.private(candidate,'config')
            with test.programs.core(config,'cudy-ss'),test.client(candidate,'10.42.0.2',network.names['zt']):
                test.ready(network.names['zt'],protocol=selected)
                before=drop_count()
                test.request(denied,namespace=network.names['zt'],allowed=False)
                assert drop_count()>before,'Private SS accepted its unselected transport'
                test.passed.extend(['private/transport/'+selected+'/allowed','private/transport/'+denied+'/denied'])
        test.model.private(raw,'rules')
        config=test.model.private(raw,'config')
        with test.programs.core(config,'cudy-ss'):
            with test.client(raw,'10.42.0.2',network.names['zt']):
                test.ready(network.names['zt'])
                test.checks('private/authorized-direct',network.names['zt'])
            for source,bind in [('lan',None),('zt','10.42.1.3')]:
                ns=network.names[source]
                with test.client(raw,'10.42.0.2',ns,source=bind):
                    before=drop_count()
                    test.checks('private/forbidden-'+('interface' if source=='lan' else 'subnet'),ns,False)
                    assert drop_count()>before,'Private SS restriction missed the production drop rule'
            run('nft','-f','-',input='''table inet fixture_policy {
chain capture { type nat hook prerouting priority -100; policy accept;
iifname "css-host" ip daddr 1.2.3.2 meta l4proto { tcp, udp } th dport 19001 redirect to :19002
}
}
''')
            with test.client(raw,'10.42.0.2',network.names['zt']):
                test.checks('private/decrypted-transparent-interception',network.names['zt'],prefix=b'PROXY|')
                established_scope_revocation(test,raw,network.names['zt'])
                test.checks('private/global-disabled-gate',network.names['zt'],False)
    finally:
        run('sh',str(script),'stop')
        network.created.remove('cudy-ss')


def established_scope_revocation(test,raw,namespace):
    payload=b'ESTABLISHED-SS-STREAM|'+os.urandom(128)
    query={'protocol':'tcp','target':test.target,'payload':base64.b64encode(payload).decode(),
        'expected':base64.b64encode(b'PROXY|'+payload).decode()}
    command=['ip','netns','exec',namespace,sys.executable,str(__file__),'--hold-query',json.dumps(query)]
    with tempfile.TemporaryFile(mode='w+t') as errors:
        child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True)
        try:
            assert child.stdout.readline().strip()=='READY','Unable to establish the private encrypted stream'
            test.model.private(raw,'rules',enabled='0')
            before=drop_count()
            child.stdin.write('CHECK\n');child.stdin.flush()
            result=child.stdout.readline().strip()
            assert child.wait(timeout=5)==0 and result=='BLOCKED', 'Established private SS connection survived scope revocation'
            assert drop_count()>before,'Established original-direction SS packet did not hit the production drop rule'
            test.passed.append('private/established-stream-scope-revoked')
        finally:
            if child.poll() is None:
                child.kill();child.wait(timeout=5)


def execute(args):
    report=Path(args.report).resolve()
    if args.root:
        # sysfs network entries belong to the netns that mounted this sysfs.
        # Production namespace ownership checks must see the test's veth alias,
        # while the runner's shared mount must never be changed.
        for kind in ('net','mnt'):
            assert os.readlink('/proc/self/ns/'+kind)!=os.readlink('/proc/1/ns/'+kind), \
                'Refusing packed tests without an isolated '+kind+' namespace'
        run('mount','-t','sysfs','sysfs','/sys')
    with tempfile.TemporaryDirectory(prefix='ss-server-e2e-',dir='/tmp' if args.root else HERE.parents[2]) as temp:
        directory=Path(temp)
        if args.root:
            root=Path(args.root).resolve()
            model=PackedModel(root,directory)
            command=['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/xray')]
            network=Network()
            try:
                network.setup()
                programs=Programs(command,directory)
                with programs.process([sys.executable,str(__file__),'--echo',str(ECHO_PORT),'DIRECT|','0.0.0.0'],network.names['wan']), \
                        programs.process([sys.executable,str(__file__),'--echo',str(PROXY_PORT),'PROXY|','0.0.0.0']):
                    verify_echo('1.2.3.2')
                    test=Acceptance(model,programs,'1.2.3.2',packed=True)
                    test.matrix();scopes(test,network)
                    private_namespace(test,network,root,directory)
            finally:
                network.close()
        else:
            model=NativeModel(args.xray_command,directory);programs=Programs(args.xray_command,directory)
            with programs.process([sys.executable,str(__file__),'--echo',str(ECHO_PORT),'DIRECT|','127.0.0.1']):
                verify_echo('127.0.0.1')
                test=Acceptance(model,programs,'127.0.0.1')
                test.matrix()
        result={'all_passed':True,'packed_arm64':bool(args.root),'encrypted_tcp_udp':True,
            'methods':model.methods,'cases':test.passed,'case_count':len(test.passed),
            'scope_and_namespace_verified':bool(args.root),'router_hardware_tested':False,
            'native_preflight_loopback_target_allow_override':not bool(args.root),
            'installed_generator_and_unmodified_server_json_verified':bool(args.root),
            'synthetic_public_target':'1.2.3.2 inside a fresh network namespace only' if args.root else None}
        if not args.root:result['unmodified_production_config_parse_checks']=model.parse_checks
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,indent=2)+'\n')
        report.chmod(0o644)
        print(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root')
    parser.add_argument('--xray-command',nargs='+')
    parser.add_argument('--report')
    parser.add_argument('--inside',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--query',help=argparse.SUPPRESS)
    parser.add_argument('--hold-query',help=argparse.SUPPRESS)
    parser.add_argument('--echo',nargs=3,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.query:
        data=json.loads(args.query)
        try:
            probe(data['protocol'],data['target'],base64.b64decode(data['payload']),base64.b64decode(data['expected']))
        except (OSError,EOFError) as error:
            print(type(error).__name__+': '+str(error),file=sys.stderr);return 1
        except Exception as error:
            print(type(error).__name__+': '+str(error),file=sys.stderr);return 2
        return 0
    if args.hold_query:
        data=json.loads(args.hold_query)
        payload=base64.b64decode(data['payload']);expected=base64.b64decode(data['expected'])
        control,_=socks_command(1,data['target'],ECHO_PORT)
        with control:
            send_frame(control,payload)
            assert receive(control,len(expected))==expected
            print('READY',flush=True)
            assert sys.stdin.readline().strip()=='CHECK'
            try:
                send_frame(control,payload)
                response=receive(control,len(expected))
            except (OSError,EOFError):
                print('BLOCKED',flush=True);return 0
            print('LEAKED',flush=True);return 2
    if args.echo:
        echo(int(args.echo[0]),args.echo[1],args.echo[2]);return 0
    if bool(args.root)==bool(args.xray_command) or not args.report:
        parser.error('choose --root or --xray-command and supply --report')
    if args.root and not args.inside:
        assert sys.platform=='linux','Packed firewall verification requires Linux namespaces'
        return subprocess.call(['sudo','unshare','--net','--mount','--propagation','private',
            sys.executable,str(Path(__file__).resolve()),
            '--root',str(Path(args.root).resolve()),'--report',str(Path(args.report).resolve()),'--inside'])
    execute(args)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
