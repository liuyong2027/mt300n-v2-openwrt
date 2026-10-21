import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

source=Path(sys.argv[1])/'package/shadowsocksr-libev-check/src/check.c'
with tempfile.TemporaryDirectory() as directory:
    binary=Path(directory)/'ssr-check'
    subprocess.run(['cc','-O2','-o',str(binary),str(source)],check=True)
    assert subprocess.run([str(binary)]).returncode==2
    assert subprocess.run([str(binary),'a'*254,'443','1']).returncode==2
    for http in [False,True]:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(5)
            def serve():
                connection,_=listener.accept()
                with connection:
                    if http:
                        assert connection.recv(8192).startswith(b'GET / HTTP/1.1')
                        connection.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK')
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            command=[str(binary),'127.0.0.1',str(listener.getsockname()[1]),'3']
            if http:command.append('1')
            subprocess.run(command,check=True,timeout=6)
            worker.join(5);assert not worker.is_alive()
print('Standalone SSR check: actual localhost TCP/HTTP and invalid arguments passed')
