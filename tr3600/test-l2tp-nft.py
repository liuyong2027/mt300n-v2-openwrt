#!/usr/bin/env python3
"""Run in a private network namespace: plaintext drops, IPsec L2TP passes."""
from pathlib import Path
import socket
import subprocess

def command(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True)

command('ip','link','set','lo','up')
rules = (Path(__file__).resolve().parent/'luci-app-cudy-l2tp/root/usr/share/nftables.d/chain-pre/input/90-cudy-l2tp.nft').read_text()
rules = 'table inet test_vpn {\nchain input {\ntype filter hook input priority 0; policy accept;\n'+rules+'\n}\n}\n'
subprocess.run(['nft','-c','-f','-'],input=rules,text=True,check=True)
subprocess.run(['nft','-f','-'],input=rules,text=True,check=True)
receiver=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
receiver.bind(('127.0.0.1',1701)); receiver.settimeout(.5)
sender=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
sender.bind(('127.0.0.2',0))
sender.sendto(b'plaintext',('127.0.0.1',1701))
try:
    receiver.recvfrom(1024)
except socket.timeout:
    pass
else:
    raise AssertionError('Plaintext L2TP reached the receiver')
# A local transport-mode SA exercises the actual nft xfrm expression.
command('ip','xfrm','state','add','src','127.0.0.2','dst','127.0.0.1','proto','esp','spi','0x100',
        'mode','transport','reqid','1','auth-trunc','hmac(sha256)','0x'+'11'*32,'128',
        'enc','cbc(aes)','0x'+'22'*16)
for direction in ('out','in'):
    command('ip','xfrm','policy','add','src','127.0.0.2/32','dst','127.0.0.1/32',
            'proto','udp','dport','1701','dir',direction,'tmpl','src','127.0.0.2','dst','127.0.0.1',
            'proto','esp','mode','transport','reqid','1','level','required')
sender.sendto(b'encrypted',('127.0.0.1',1701))
payload,_=receiver.recvfrom(1024)
assert payload == b'encrypted'
sender.close(); receiver.close()
print('Actual nftables plaintext rejection and IPsec transport acceptance passed')
