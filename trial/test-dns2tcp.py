#!/usr/bin/env python3
"""Run the compiled MIPS DNS2TCP against a real local TCP DNS fixture."""
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
import time

root=Path(sys.argv[1]).resolve()
output=Path(sys.argv[2])
query=struct.pack('!6H',0x5a4f,0x100,1,0,0,0)+b'\x07fixture\x07example\0'+struct.pack('!HH',1,1)
answer=query[:2]+struct.pack('!5H',0x8180,1,1,0,0)+query[12:]+b'\xc0\x0c'+struct.pack('!HHIH',1,1,60,4)+socket.inet_aton('198.51.100.42')
stop=threading.Event()
drop=threading.Event()
failures=[]
def receive(connection,size):
    data=b''
    while len(data)<size:
        chunk=connection.recv(size-len(data))
        if not chunk:raise RuntimeError('Unexpected fixture EOF')
        data+=chunk
    return data
with socket.socket() as listener:
    listener.bind(('127.0.0.1',0));listener.listen(4);listener.settimeout(.2)
    tcp_port=listener.getsockname()[1]
    def serve():
        while not stop.is_set():
            try:connection,_=listener.accept()
            except socket.timeout:continue
            except OSError:return
            try:
                with connection:
                    connection.settimeout(2)
                    size=struct.unpack('!H',receive(connection,2))[0]
                    request=receive(connection,size)
                    assert request==query
                    if not drop.is_set():connection.sendall(struct.pack('!H',len(answer))+answer)
            except Exception as error:failures.append(str(error))
    worker=threading.Thread(target=serve,daemon=True);worker.start()
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as reserve:
        reserve.bind(('127.0.0.1',0));udp_port=reserve.getsockname()[1]
    command=['qemu-mipsel-static','-L',str(root),str(root/'usr/bin/dns2tcp'),
             '-L',f'127.0.0.1#{udp_port}','-R',f'127.0.0.1#{tcp_port}']
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    def request(deadline=10):
        until=time.monotonic()+deadline
        while time.monotonic()<until:
            assert process.poll() is None,'Compiled DNS2TCP exited'
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
                client.settimeout(.5);client.sendto(query,('127.0.0.1',udp_port))
                try:reply,_=client.recvfrom(4096)
                except socket.timeout:continue
                assert reply==answer,'Unexpected DNS response'
                return
        raise AssertionError('Compiled DNS2TCP did not forward the DNS query')
    try:
        request()
        drop.set()
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
            client.settimeout(.5);client.sendto(query,('127.0.0.1',udp_port))
            try:client.recvfrom(4096)
            except socket.timeout:pass
        assert process.poll() is None,'DNS2TCP died after upstream EOF'
        drop.clear();request()
        assert not failures,failures
        result={'status':'passed','scope':'actual compiled MIPS DNS2TCP under QEMU; real UDP/TCP loopback DNS',
                'udp_request_tcp_forward_response':True,'survives_upstream_eof':True,'recovers_after_upstream_eof':True}
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result))
    finally:
        process.terminate()
        try:process.communicate(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.communicate(timeout=3)
        stop.set();worker.join(2)
