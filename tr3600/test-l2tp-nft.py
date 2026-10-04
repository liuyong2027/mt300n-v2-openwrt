#!/usr/bin/env python3
"""Run in a private network namespace: plaintext drops, IPsec L2TP passes."""
from pathlib import Path
import os
import socket
import subprocess

def command(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True)

command('ip','link','set','lo','up')
rules = (Path(__file__).resolve().parent/'luci-app-cudy-l2tp/root/usr/share/nftables.d/chain-pre/input/90-cudy-l2tp.nft').read_text()
rules = 'table inet test_vpn {\nchain input {\ntype filter hook input priority 0; policy accept;\n'+rules+'\n}\n}\n'
subprocess.run(['nft','-c','-f','-'],input=rules,text=True,check=True)
subprocess.run(['nft','-f','-'],input=rules,text=True,check=True)
client = 'cudy-l2tp-test-'+str(os.getpid())
command('ip','netns','add',client)
try:
    command('ip','link','add','vpnserver','type','veth','peer','name','vpnclient')
    command('ip','link','set','vpnclient','netns',client)
    command('ip','addr','add','10.77.0.1/24','dev','vpnserver')
    command('ip','link','set','vpnserver','up')
    command('ip','netns','exec',client,'ip','addr','add','10.77.0.2/24','dev','vpnclient')
    command('ip','netns','exec',client,'ip','link','set','vpnclient','up')
    command('ip','netns','exec',client,'ip','link','set','lo','up')
    receiver=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    receiver.bind(('10.77.0.1',1701)); receiver.settimeout(1)
    def send(payload):
        script = 'import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto('+repr(payload)+',("10.77.0.1",1701)); s.close()'
        command('ip','netns','exec',client,'python3','-c',script)
    send(b'plaintext')
    try:
        receiver.recvfrom(1024)
    except socket.timeout:
        pass
    else:
        raise AssertionError('Plaintext L2TP reached the receiver')
    # Real traffic crosses the veth link between separate IPsec endpoints.
    for prefix,direction in [((),'in'),(('ip','netns','exec',client),'out')]:
        command(*prefix,'ip','xfrm','state','add','src','10.77.0.2','dst','10.77.0.1','proto','esp','spi','0x100',
                'mode','transport','reqid','1','auth-trunc','hmac(sha256)','0x'+'11'*32,'128',
                'enc','cbc(aes)','0x'+'22'*16)
        command(*prefix,'ip','xfrm','policy','add','src','10.77.0.2/32','dst','10.77.0.1/32',
                'proto','udp','dport','1701','dir',direction,'tmpl','src','10.77.0.2','dst','10.77.0.1',
                'proto','esp','mode','transport','reqid','1','level','required')
    send(b'encrypted')
    receiver.settimeout(3)
    payload,_=receiver.recvfrom(1024)
    assert payload == b'encrypted'
    receiver.close()
finally:
    command('ip','netns','delete',client)
print('Actual nftables plaintext rejection and IPsec transport acceptance passed')
