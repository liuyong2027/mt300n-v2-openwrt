#!/usr/bin/env python3
"""Use real sockets and the actual nft output function to detect proxy self-loops."""
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

root=Path(sys.argv[1])/'package/luci-app-ssr-plus/root'
def function(text,name):
    start=text.index(name+'() {\n');end=text.index('\n}\n',start)+3
    return text[start:end]
ac=function((root/'usr/bin/ssr-rules').read_text(encoding='utf-8'),'ac_rule_nft').replace('ss_spec','mark_fixture')
subprocess.run(['ip','link','set','lo','up'],check=True)
subprocess.run(['ip','addr','add','198.18.0.1/32','dev','lo'],check=True)
stop=threading.Event()
listeners=[];workers=[]
def endpoint(label):
    listener=socket.socket();listener.bind(('0.0.0.0',0));listener.listen(4);listener.settimeout(.2)
    listeners.append(listener)
    def serve():
        while not stop.is_set():
            try:connection,_=listener.accept()
            except socket.timeout:continue
            except OSError:return
            with connection:connection.sendall(label)
    worker=threading.Thread(target=serve,daemon=True);worker.start();workers.append(worker)
    return listener.getsockname()[1]
direct_port=endpoint(b'DIRECT')
proxy_port=endpoint(b'PROXY')
try:
    with tempfile.TemporaryDirectory() as directory:
        setup=Path(directory)/'setup.sh'
        setup.write_text('''#!/bin/bash
set -e
NFT='nft -nn -t'
OUTPUT=1
TCP_EXT_ARGS='meta l4proto tcp'
TAG=_SS_SPEC_RULE_
loger() { printf '%s\\n' "$2"; }
'''+ac+f'''
nft -f - <<'NFT'
table inet mark_fixture {{
 chain mark_fixture_wan_fw {{ tcp dport {direct_port} counter redirect to :{proxy_port}; }}
 chain mark_fixture_wan_ac {{ jump mark_fixture_wan_fw; }}
}}
NFT
ac_rule_nft
''',encoding='utf-8')
        subprocess.run(['bash',str(setup)],check=True)
        def connection(mark):
            with socket.socket() as client:
                client.settimeout(3)
                if mark:client.setsockopt(socket.SOL_SOCKET,socket.SO_MARK,mark)
                client.connect(('198.18.0.1',direct_port))
                return client.recv(32)
        for phase in ['fresh','after_cache_reload']:
            assert connection(0)==b'PROXY','Ordinary traffic escaped the transparent proxy'
            assert connection(255)==b'DIRECT','Xray marked egress was proxied again'
            if phase=='fresh':
                dump=subprocess.check_output(['nft','-nn','-s','list','table','inet','mark_fixture'],text=True)
                cache=Path(directory)/'reload.nft'
                cache.write_text('destroy table inet mark_fixture\n'+dump,encoding='utf-8')
                subprocess.run(['nft','-f',str(cache)],check=True)
        print('MARKED_XRAY_EGRESS_BYPASS_AND_ORDINARY_PROXY=passed')
        print('MARK_BYPASS_SURVIVES_CACHE_RELOAD=passed')
finally:
    stop.set()
    for listener in listeners:listener.close()
    for worker in workers:worker.join(1)
    subprocess.run(['nft','destroy','table','inet','mark_fixture'],check=False)
    subprocess.run(['ip','addr','del','198.18.0.1/32','dev','lo'],check=False)

# A failed bootstrap resolver must not hold the service lock indefinitely.
get_host=function((root/'etc/init.d/shadowsocksr').read_text(encoding='utf-8'),'get_host_ip')
halt=threading.Event()
with socket.socket() as listener:
    listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(8)
    port=listener.getsockname()[1]
    def stall():
        try:
            connection,_=listener.accept()
            with connection:halt.wait(8)
        except OSError:pass
    worker=threading.Thread(target=stall,daemon=True);worker.start()
    get_host=get_host.replace('http://119.29.29.29/d?dn=$host',f'http://127.0.0.1:{port}/d?dn=$host')
    harness='''#!/bin/bash
resolveip() { return 1; }
uci_get_by_name() { case "$2" in server) echo fixture.example ;; ip) echo 192.0.2.1 ;; esac; }
uci_get_by_type() { :; }
uci_set_by_name() { :; }
'''+get_host+'\nget_host_ip fixture\n'
    try:
        start=time.monotonic()
        result=subprocess.run(['bash'],input=harness,text=True,capture_output=True,check=True,timeout=9)
        elapsed=time.monotonic()-start
        assert result.stdout.strip()=='192.0.2.1',result.stdout
        assert 4<=elapsed<7.5,elapsed
        print(f'BOOTSTRAP_RESOLVER_TIMEOUT_BOUNDED=passed SECONDS={elapsed:.2f}')
    finally:halt.set();worker.join(1)
