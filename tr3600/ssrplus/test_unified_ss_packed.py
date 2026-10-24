"""Actual packed ARM64 SS, nft ingress, REDIRECT and UDP TPROXY in fresh namespaces."""
import argparse
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import test_ss_server as old

HERE=Path(__file__).resolve().parent

class Model(old.PackedModel):
    def __init__(self,root,directory):
        super().__init__(root,directory)
        self.driver.write_text('''local root,conf,saved,action=arg[1],arg[2],arg[3],arg[4]
local native=require('uci');local original=native.cursor
native.cursor=function()return assert(original(conf,saved))end
local json=require('luci.jsonc');local real_dofile=dofile
dofile=function(path)
 if path:sub(1,17)=='/usr/lib/cudy-ss/' then path=root..path end
 return real_dofile(path)
end
local model=require('cudy.ssr-server')
if action=='methods' then print(json.stringify(model.methods));return end
local runtime=dofile('/usr/lib/cudy-ss/server-runtime.lua')
if action=='config' then dofile(root..'/usr/share/shadowsocksr/gen_cudy_ss_server.lua')
elseif action=='probe' then
 local fs=require('nixio.fs');local read,access=fs.readfile,fs.access
 fs.readfile=function(p)if p=='/var/etc/cudy-ss/config.json' then p=conf..'/loaded.json' end;return read(p)end
 fs.access=function(p)if p=='/var/run/cudy-ss/core-ready' then return true end;return access(p)end
 local popen=io.popen;local pid=assert(tonumber(os.getenv('SS_TEST_PID')))
 io.popen=function(command,mode)
  if command=='/usr/libexec/cudy-ss-process snapshot' then command='printf "'..pid..':1 "' end
  return popen(command,mode)
 end
 print(runtime.ready() and 'READY' or 'CLOSED')
else
 local lan=action=='no-lan' and {} or {device='lanfixture',addresses={'10.99.0.1'}}
 io.write(model.rules(runtime.rows(),lan,action=='closed-rules' and {} or nil))
end
''')

    def fixture(self,raw,enabled='1'):
        rows=raw if isinstance(raw,list) else [raw]
        lines=["config server_global 'sg'"," option enable_server '"+enabled+"'"]
        for entry in rows:
            lines.append("config server_config '"+entry['.name']+"'")
            for k,v in entry.items():
                if k.startswith('.'):continue
                assert "'" not in str(v) and '\n' not in str(v)
                lines.append(" option "+k+" '"+str(v)+"'")
        (self.conf/'shadowsocksr').write_text('\n'.join(lines)+'\n')

    def rules(self,raw,active=True,enabled='1',lan=True):
        self.fixture(raw,enabled)
        old.run('nft','-f','-',input=self.lua('closed-rules' if not active else ('rules' if lan else 'no-lan')))

    def probe(self,config,pid,expected=True):
        (self.conf/'loaded.json').write_text(json.dumps(config))
        self.environment['SS_TEST_PID']=str(pid)
        deadline=time.monotonic()+8
        while True:
            actual=self.lua('probe').strip()
            if actual==('READY' if expected else 'CLOSED'):return
            assert time.monotonic()<deadline,(actual,expected)
            time.sleep(.1)

class Programs(old.Programs):
    def core(self,config,namespace=None):
        if any(i.get('protocol')=='shadowsocks' for i in config.get('inbounds',[])):namespace='cudy-ss'
        return super().core(config,namespace)

def network_setup(network):
    network.setup()
    old.run('nft','-f','-',input='''add chain inet fw4 CUDY_SSR_SS_FORWARD
add chain inet fw4 forward { type filter hook forward priority 0; policy drop; }
add rule inet fw4 forward ct state established,related accept
add rule inet fw4 forward jump CUDY_SSR_SS_FORWARD
add rule inet fw4 forward iifname "css-host" accept
add rule inet fw4 input iifname "css-host" accept
''')

@contextmanager
def namespace(network,root,directory):
    helper=(root/'usr/libexec/cudy-ss-netns').read_text()
    helper=helper.replace('dir=/var/run/cudy-ss','dir='+str(directory/'run'))
    helper=helper.replace('/var/lock/cudy-ss-netns.lock',str(directory/'namespace.lock'))
    helper=helper.replace('lua /usr/lib/cudy-ss/check-prefix.lua','lua5.1 '+str(root/'usr/lib/cudy-ss/check-prefix.lua'))
    path=directory/'namespace';path.write_text(helper)
    old.run('sh',str(path),'start');network.created.append('cudy-ss')
    old.run('sysctl','-w','net.ipv4.conf.css-host.route_localnet=1',stdout=subprocess.DEVNULL)
    try:yield
    finally:
        old.run('sh',str(path),'stop');network.created.remove('cudy-ss')

def scopes(test,network):
    for scope in ('loopback','lan','public'):
        raw=old.row(scope=scope);config=test.model.config(raw);test.model.rules(raw)
        with test.programs.core(config) as core:
            test.model.probe(config,core.pid)
            for source,dest in [('lan','10.99.0.1'),('wan','1.2.3.1'),('zt','10.42.0.2')]:
                ns=network.names[source];allowed=scope=='public' or (scope=='lan' and source=='lan')
                with test.client(raw,dest,ns):
                    if allowed:test.ready(ns)
                    before=old.drop_count();test.checks('scope/'+scope+'/'+source,ns,allowed)
                    if not allowed:assert old.drop_count()>before
            with test.client(raw,'127.0.0.1'):
                test.ready();test.checks('scope/'+scope+'/router-loopback')
            with test.client(raw,'198.18.255.2',network.names['lan']):
                before=old.drop_count();test.checks('scope/'+scope+'/direct-peer',network.names['lan'],False)
                assert old.drop_count()>before
            if scope=='lan':
                with test.client(raw,'10.42.0.2',network.names['lan']):
                    test.checks('scope/lan/wrong-destination',network.names['lan'],False)
                test.model.rules(raw,lan=False)
                with test.client(raw,'10.99.0.1',network.names['lan']):
                    test.checks('scope/lan/missing-interface',network.names['lan'],False)

    # Multiple configured servers share one core, retaining independent scopes.
    first=old.row(scope='public');second=dict(old.row(scope='lan'),**{'.name':'second','server_port':'18389'})
    rows=[first,second];config=test.model.config(rows);test.model.rules(rows)
    with test.programs.core(config) as core:
        test.model.probe(config,core.pid)
        test.model.probe(config,os.getpid(),expected=False)
        for raw in rows:
            with test.client(raw,'10.99.0.1',network.names['lan']):
                test.ready(network.names['lan']);test.checks('shared-core/'+raw['.name'],network.names['lan'])
        test.passed.append('readiness/native-owned-sockets-positive-and-foreign-process-negative')

def policy(test,network,root,directory):
    # The existing SSR chains contain a synthetic deterministic policy. TCP uses
    # real REDIRECT; UDP uses real TPROXY and a marked local route. The installed
    # interface helper attaches SS exactly as it does on the router.
    old.run('ip','rule','add','pref','10000','fwmark','1/255','lookup','100')
    old.run('ip','route','add','local','0.0.0.0/0','dev','lo','table','100')
    old.run('nft','-f','-',input='''table inet ss_spec {
chain ss_spec_wan_ac { ip daddr 1.2.3.2 tcp dport 19001 counter redirect to :19003;
tcp dport 19004 counter drop
}
chain ss_spec_output { type nat hook output priority 0; policy accept;
ip daddr 198.18.255.2 tcp dport 18388 counter redirect to :19003
}
chain ss_spec_prerouting { type nat hook prerouting priority 0; policy accept;
iifname "css-host" ct direction reply counter drop
iifname "css-host" tcp dport 19001 jump ss_spec_wan_ac
}
}
table ip ss_spec_mangle {
chain ss_spec_tproxy { ip daddr 198.18.255.2 udp dport 18388 counter drop
ip daddr 1.2.3.2 udp dport 19001 counter meta mark set 1 tproxy to :19003 accept;
udp dport 19004 counter drop
}
chain prerouting { type filter hook prerouting priority -150; policy accept;
iifname "css-host" ct direction reply counter drop
iifname "css-host" udp dport 19001 jump ss_spec_tproxy
# A synthetic monitored LAN exercises protection of encrypted UDP ingress.
iifname "lanfixture" meta l4proto udp counter jump ss_spec_tproxy
}
}
add rule inet fw4 input meta mark 1 accept
''')
    shim=directory/'bin';shim.mkdir();uci=shim/'uci';uci.write_text('#!/bin/sh\nexit 1\n');uci.chmod(0o755)
    env=os.environ.copy();env['PATH']=str(shim)+':'+env['PATH']
    old.run('sh',str(root/'usr/libexec/cudy-ss-ssr-interfaces'),env=env)
    before=subprocess.check_output(['nft','list','ruleset'],text=True)
    old.run('sh',str(root/'usr/libexec/cudy-ss-ssr-interfaces'),env=env)
    assert before==subprocess.check_output(['nft','list','ruleset'],text=True),'Interface hooks are not idempotent'
    transparent={'log':{'loglevel':'warning'},'inbounds':[{'listen':'0.0.0.0','port':19003,
        'protocol':'dokodemo-door','settings':{'network':'tcp,udp','followRedirect':True},
        'streamSettings':{'sockopt':{'tproxy':'tproxy'}}}],
        'outbounds':[{'protocol':'freedom','settings':{'redirect':'1.2.3.2:19002'},
            'streamSettings':{'sockopt':{'mark':255}}}]}
    raw=old.row(scope='public');config=test.model.config(raw);test.model.rules(raw)
    with test.programs.core(transparent),test.programs.core(config):
        with test.client(raw,'127.0.0.1'):
            test.checks('policy/router-encrypted-OUTPUT-not-recaptured',prefix=b'PROXY|')
        with test.client(raw,'10.99.0.1',network.names['lan']):
            test.checks('policy/decrypted-TCP-REDIRECT-and-UDP-TPROXY',network.names['lan'],prefix=b'PROXY|')
            test.checks('policy/unselected-proxy-port-stays-direct',network.names['lan'],echo_port=19004)
            previous=test.target;test.target='1.2.3.3'
            try:test.checks('policy/bypass-destination-stays-direct',network.names['lan'])
            finally:test.target=previous
            revoke(test,raw,network.names['lan'])
        test.model.rules(raw)
        with test.client(raw,'10.99.0.1',network.names['lan']):
            test.checks('policy/access-restored',network.names['lan'],prefix=b'PROXY|')
        for label,candidate,enabled in [('row-disabled',dict(raw,enable='0'),'1'),('global-disabled',raw,'0')]:
            test.model.rules(candidate,enabled=enabled)
            with test.client(raw,'10.99.0.1',network.names['lan']):test.checks(label,network.names['lan'],False)
        # Reopening valid state must recover without stale DNAT/TPROXY failures.
        test.model.rules(raw)
        with test.client(raw,'10.99.0.1',network.names['lan']):test.checks('policy/re-enabled',network.names['lan'],prefix=b'PROXY|')
    data=json.loads(subprocess.check_output(['nft','-j','list','ruleset'],text=True))
    replies=0;captured={'tcp':0,'udp':0}
    for item in data['nftables']:
        rule=item.get('rule',{});count=sum(e.get('counter',{}).get('packets',0) for e in rule.get('expr',[]))
        if rule.get('comment')=='Cudy SS encrypted reply':replies+=count
        if rule.get('chain')=='ss_spec_wan_ac':captured['tcp']+=count
        if rule.get('chain')=='ss_spec_tproxy':captured['udp']+=count
        if rule.get('chain') in ('ss_spec_prerouting','prerouting') and any('drop' in e for e in rule.get('expr',[])):
            assert count==0,'Encrypted replies reached the downstream trap'
    assert replies>0 and all(v>0 for v in captured.values()),(replies,captured)
    test.passed.append('policy/production-reply-bypass-and-both-capture-counters')

def revoke(test,raw,ns):
    payload=b'ESTABLISHED-ORDINARY-SS|'+os.urandom(128)
    query={'target':test.target,'payload':base64.b64encode(payload).decode(),
        'expected':base64.b64encode(b'PROXY|'+payload).decode()}
    with tempfile.TemporaryFile(mode='w+t') as errors:
        child=subprocess.Popen(['ip','netns','exec',ns,sys.executable,str(HERE/'test_ss_server.py'),
            '--hold-query',json.dumps(query)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True)
        try:
            assert child.stdout.readline().strip()=='READY'
            test.model.rules(dict(raw,cudy_access='loopback'))
            child.stdin.write('CHECK\n');child.stdin.flush()
            assert child.stdout.readline().strip()=='BLOCKED' and child.wait(timeout=5)==0
            test.passed.append('scope/established-encrypted-stream-revoked')
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=5)

def execute(args):
    for kind in ('net','mnt'):
        assert os.readlink('/proc/self/ns/'+kind)!=os.readlink('/proc/1/ns/'+kind)
    old.run('mount','-t','sysfs','sysfs','/sys')
    root=Path(args.root).resolve();report=Path(args.report).resolve()
    with tempfile.TemporaryDirectory(prefix='unified-ss-',dir='/tmp') as temp:
        directory=Path(temp);model=Model(root,directory)
        programs=Programs([args.qemu,'-L',str(root),str(root/'usr/bin/xray')],directory)
        network=old.Network()
        try:
            network_setup(network)
            old.run('ip','-n',network.names['wan'],'address','add','1.2.3.3/24','dev','ss-peer-wan')
            with namespace(network,root,directory),\
                programs.process([sys.executable,str(HERE/'test_ss_server.py'),'--echo',str(old.ECHO_PORT),'DIRECT|','0.0.0.0'],network.names['wan']),\
                programs.process([sys.executable,str(HERE/'test_ss_server.py'),'--echo',str(old.PROXY_PORT),'PROXY|','0.0.0.0'],network.names['wan']),\
                programs.process([sys.executable,str(HERE/'test_ss_server.py'),'--echo','19004','DIRECT|','0.0.0.0'],network.names['wan']):
                old.verify_echo('1.2.3.2');test=old.Acceptance(model,programs,'1.2.3.2',packed=True)
                test.matrix();scopes(test,network);policy(test,network,root,directory)
        finally:network.close()
        result={'all_passed':True,'packed_arm64':True,'methods':model.methods,'cases':test.passed,
            'case_count':len(test.passed),'real_udp_tproxy':True,'production_generators_unmodified':True,
            'router_hardware_tested':False,'private_ss_runtime_present':False}
        report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,indent=2)+'\n');report.chmod(0o644)
        print(json.dumps(result,indent=2))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--report',required=True)
    parser.add_argument('--qemu',default='qemu-aarch64-static');parser.add_argument('--inside',action='store_true')
    args=parser.parse_args()
    if not args.inside:
        return subprocess.call(['sudo','unshare','--net','--mount','--propagation','private',sys.executable,
            str(Path(__file__).resolve()),'--root',str(Path(args.root).resolve()),'--report',str(Path(args.report).resolve()),
            '--qemu',args.qemu,'--inside'])
    execute(args);return 0

if __name__=='__main__':raise SystemExit(main())
