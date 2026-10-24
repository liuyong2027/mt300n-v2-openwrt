"""Real namespace/NAT tests. Run only inside a fresh Linux network namespace."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE=Path(__file__).resolve().parent
def run(*args,**kwargs):return subprocess.run(args,check=True,text=True,**kwargs)
def serve(port,label):
    def udp():
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('0.0.0.0',port))
        while True:
            data,peer=sock.recvfrom(2048);sock.sendto(label.encode(),peer)
    threading.Thread(target=udp,daemon=True).start()
    sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    sock.bind(('0.0.0.0',port));sock.listen()
    while True:
        peer,_=sock.accept();peer.recv(2048);peer.sendall(label.encode());peer.close()
def query(proto,address,port,bind=None):
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM if proto=='udp' else socket.SOCK_STREAM)
    sock.settimeout(1)
    if bind:sock.bind((bind,0))
    try:
        sock.connect((address,port));sock.send(b'fixture');return sock.recv(2048).decode()
    finally:sock.close()
def inside():
    assert os.geteuid()==0
    names=['cudy-ss','ssr-zt-test','ssr-wan-test','ssr-lan-test']
    existing=run('ip','netns','list',capture_output=True).stdout
    for name in names:assert name not in existing,'Refusing an existing test namespace'
    children=[];created=[]
    with tempfile.TemporaryDirectory(prefix='cudy-network-') as temp:
        temp=Path(temp)
        def ip(*args):run('ip',*args,stdout=subprocess.DEVNULL)
        def pair(name,host,peer,rootip,childip):
            ip('netns','add',name);created.append(name)
            ip('link','add',host,'type','veth','peer','name',peer)
            ip('link','set',peer,'netns',name)
            ip('addr','add',rootip+'/24','dev',host);ip('link','set',host,'up')
            ip('netns','exec',name,'ip','link','set','lo','up')
            ip('netns','exec',name,'ip','addr','add',childip+'/24','dev',peer)
            ip('netns','exec',name,'ip','link','set',peer,'up')
            ip('netns','exec',name,'ip','route','add','default','via',rootip)
        def launch(ns,port,label):
            cmd=[sys.executable,str(__file__),'serve',str(port),label]
            if ns:cmd=['ip','netns','exec',ns]+cmd
            child=subprocess.Popen(cmd);children.append(child)
        def request(ns,proto,address,port,expected,bind=None):
            cmd=['ip','netns','exec',ns,sys.executable,str(__file__),'query',proto,address,str(port)]
            if bind:cmd.append(bind)
            result=subprocess.run(cmd,capture_output=True,text=True)
            if expected is None:assert result.returncode!=0,(proto,result.stdout)
            else:assert result.returncode==0 and result.stdout.strip()==expected,(proto,result.stdout,result.stderr)
        try:
            run('sysctl','-w','net.ipv4.ip_forward=1',stdout=subprocess.DEVNULL)
            pair('ssr-zt-test','ztfixture','zt-peer','10.42.0.2','10.42.0.3')
            pair('ssr-wan-test','wanfixture','wan-peer','203.0.113.1','203.0.113.2')
            pair('ssr-lan-test','lanfixture','lan-peer','10.99.0.1','10.99.0.2')
            helper=(HERE/'root/usr/libexec/cudy-ss-netns').read_text()
            helper=helper.replace('dir=/var/run/cudy-ss','dir='+str(temp/'run'))
            helper=helper.replace('/var/lock/cudy-ss-netns.lock',str(temp/'namespace.lock'))
            helper=helper.replace('/usr/lib/cudy-ss/check-prefix.lua',str(HERE/'root/usr/lib/cudy-ss/check-prefix.lua'))
            path=temp/'netns';path.write_text(helper)
            run('sh',str(path),'start');created.append('cudy-ss')
            lua='local n=dofile('+json.dumps(str(HERE/'config.lua'))+');io.write(n.guard({listen="10.42.0.2",subnet="10.42.0.0/24",interface="ztfixture",port=8388,network="tcp,udp"}))'
            rules=run('lua5.1','-e',lua,capture_output=True).stdout
            run('nft','-f','-',input=rules)
            bridge=lua.replace('io.write(n.guard(', 'io.write(n.bridge(nil,')
            run('nft','-c','-f','-',input=run('lua5.1','-e',bridge,capture_output=True).stdout)
            launch('cudy-ss',8388,'SS')
            launch('ssr-wan-test',19001,'DIRECT')
            launch(None,19002,'PROXY')
            time.sleep(.5)
            for proto in ['tcp','udp']:
                request('ssr-zt-test',proto,'10.42.0.2',8388,'SS')
                request('ssr-lan-test',proto,'10.42.0.2',8388,None)
                request('cudy-ss',proto,'203.0.113.2',19001,'DIRECT')
            # This emulates a transparent policy's local interception point.
            # Both decrypted protocols must reach it through css-host.
            run('nft','-f','-',input='''table inet fixture_policy {
chain capture { type nat hook prerouting priority -100; policy accept;
iifname "css-host" ip daddr 203.0.113.2 meta l4proto { tcp, udp } th dport 19001 redirect to :19002
}
}
''')
            for proto in ['tcp','udp']:
                request('cudy-ss',proto,'203.0.113.2',19001,'PROXY')
            run('nft','-f','-',input='''table inet fixture_gate {
chain gate { type filter hook prerouting priority -312; policy accept;
iifname "css-host" ct direction reply return
iifname "css-host" drop
}
}
''')
            for proto in ['tcp','udp']:
                request('cudy-ss',proto,'203.0.113.2',19001,None)
            print('PASS real ZeroTier scope, TCP/UDP routing, transparent interception and closed gate')
        finally:
            for child in children:child.terminate()
            for child in children:child.wait(timeout=5)
            for name in reversed(created):run('ip','netns','del',name)

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='serve':serve(int(sys.argv[2]),sys.argv[3])
    elif len(sys.argv)>1 and sys.argv[1]=='query':
        try:print(query(sys.argv[2],sys.argv[3],int(sys.argv[4]),sys.argv[5] if len(sys.argv)>5 else None))
        except (OSError,TimeoutError):sys.exit(1)
    elif '--inside' in sys.argv:inside()
    else:run('sudo','unshare','--net',sys.executable,str(__file__),'--inside')

