#!/usr/bin/env python3
"""Exercise actual pinned shell functions, only in a private network namespace."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import urllib.request

assert Path('/proc/self/ns/net').readlink()!=Path('/proc/1/ns/net').readlink()
BASE='https://raw.githubusercontent.com/fw876/helloworld/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus/root/'
def fetch(name):
    return (Path('validation-input')/name).read_text()
init=fetch('etc/init.d/shadowsocksr')
rules=fetch('usr/bin/ssr-rules')
start_dns=init[init.index('start_dns() {'):init.index('\ngen_service_file() {')]
def function(name,next_name):
    return rules[rules.index(name+'() {'):rules.index('\n'+next_name+'() {')]
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)
    fixture=r'''
set -e
HAS_IPSET=0
dns_port=5335
china_dns_port=5333
TMP_DNSMASQ_PATH="$1"
uci_get_by_type() {
    case "$1.$2" in
      global.pdnsd_enable) echo 1;;
      global.run_mode) echo router;;
      global.tunnel_forward) echo 1.1.1.1:53;;
      global.chinadns_forward) printf '%s\n' "$DNS_CASE";;
      global.apple_optimization) echo 0;;
      *) printf '%s\n' "$3";;
    esac
}
first_type() { [ "$1" = dns2tcp ] && echo dns2tcp; }
ln_start_bin() { [ "$1" = dns2tcp ] || exit 72; }
ifstatus() { echo '{"dns-server":["119.29.29.29"]}'; }
jsonfilter() { echo 119.29.29.29; }
echolog() { :; }
'''
    script=path/'dns.sh';script.write_text(fixture+start_dns+'\nstart_dns\n')
    import os
    bad=subprocess.run(['bash',str(script),str(path)],env=dict(os.environ,DNS_CASE='none'),capture_output=True)
    good=subprocess.run(['bash',str(script),str(path)],env=dict(os.environ,DNS_CASE=''),capture_output=True)
    assert bad.returncode!=0,'Reference none value must reproduce missing-core startup failure'
    assert good.returncode==0,good.stderr.decode()
    # Use the unmodified upstream routing functions in a private nft namespace.
    code=function('ipset_nft','ipset_iptables')+function('fw_rule_nft','fw_rule_iptables')+function('ac_rule_nft','ac_rule_iptables')
    script=path/'rules.sh'
    script.write_text('''#!/bin/bash
NFT=nft
USE_NFT=1
RUNMODE=gfw
OUTPUT=1
server=198.51.100.10
local_port=12345
SHUNT_PORT=0
SHUNT_LIST=/nonexistent
IGNORE_LIST=/nonexistent
xhttp_ip=/nonexistent
TAG=test-ssrp
FWMARK=0x53535250
WAN_FW_IP="$1"
loger() { :; }
'''+code+'\nipset_nft\nfw_rule_nft\nac_rule_nft\n')
    subprocess.run(['ip','link','set','lo','up'],check=True)
    subprocess.run(['ip','addr','add','1.1.1.1/32','dev','lo'],check=True)
    results=[]
    for forced,expected in [('',False),('1.1.1.1',True)]:
        subprocess.run(['nft','delete','table','inet','ss_spec'],capture_output=True)
        subprocess.run(['bash',str(script),forced],check=True,capture_output=True)
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as receiver:
            receiver.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            receiver.bind(('0.0.0.0',12345));receiver.listen(2);receiver.settimeout(.25)
            connected=False
            try:
                with socket.create_connection(('1.1.1.1',53),timeout=.5):pass
                connection,_=receiver.accept();connection.close();connected=True
            except (ConnectionRefusedError,TimeoutError,socket.timeout):pass
            assert connected==expected,(forced,connected)
            results.append({'forced_dns_ip':bool(forced),'tcp53_redirected_to_proxy':connected})
    subprocess.run(['nft','delete','table','inet','ss_spec'],check=True)
out=Path('validation-output');out.mkdir(exist_ok=True)
result={'status':'passed','empty_chinadns_without_extra_core':'passed',
    'reference_none_value_reproduced_failure':True,'gfw_dns_packets':results,
    'scope':'actual pinned upstream functions; localhost startup fixture and real isolated nft TCP packets'}
(out/'DNS-BACKEND-VALIDATION.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
