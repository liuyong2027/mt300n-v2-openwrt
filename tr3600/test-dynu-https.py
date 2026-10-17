"""Exercise actual packed ARM64 Lua/jsonc and BusyBox; synthetic credentials only."""
import json, os, pathlib, subprocess, sys, tempfile

root=pathlib.Path(sys.argv[1]).resolve()
source=pathlib.Path(sys.argv[2]).resolve()
env=dict(os.environ,LUA_CPATH=str(root/'usr/lib/lua/?.so'),LUA_PATH=str(root/'usr/lib/lua/?.lua')+';'+str(root/'usr/lib/lua/?/init.lua'))
lua=['qemu-aarch64-static','-L',str(root),str(root/'usr/bin/lua')]
resolver=source/'usr/libexec/cudy-dynu-resolve'
count=0
def check(name,args,expected,input=None):
    global count
    p=subprocess.run(args,input=input,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    assert (p.returncode==0)==expected,(name,p.returncode,p.stderr)
    count+=1;print('PASS Dynu: '+name)
    return p.stdout
def answer(v,name='api.dynu.com.'):return {'name':name,'type':1,'data':v}
cases=[('public/dedup',{'Status':0,'Answer':[answer('162.216.242.28'),answer('162.216.242.28'),answer('192.168.0.101')]},True),
 ('private/reserved',{'Status':0,'Answer':[answer(v)for v in ('127.0.0.1','10.0.0.1','100.64.0.1','172.16.0.1','192.168.0.101','169.254.1.1','203.0.113.1','999.1.1.1')]},False),
 ('wrong hostname',{'Status':0,'Answer':[answer('162.216.242.28','other.example.')]},False),
 ('DNS failure',{'Status':3,'Answer':[answer('162.216.242.28')]},False),
 ('truncated',{'Status':0,'TC':True,'Answer':[answer('162.216.242.28')]},False),('malformed','not JSON',False),
 ('bounded output','x'*65537,False)]
for name,data,passed in cases:
    out=check(name,lua+[str(resolver),'--validate-json'],passed,json.dumps(data)if not isinstance(data,str)else data)
    if name=='public/dedup':assert out.strip()=='162.216.242.28'
check('migration',lua+[str(pathlib.Path(__file__).with_name('test-dynu-migration.lua')),str(source/'usr/lib/lua/cudy/dynu-migrate.lua')],True)
with tempfile.TemporaryDirectory(prefix='cudy-dynu-fixtures-')as td:
    td=pathlib.Path(td)
    conf=td/'config';conf.mkdir();saved=td/'saved';saved.mkdir()
    (conf/'ddns').write_text("config ddns 'global'\nconfig service 'fixture'\n option service_name 'dynu.com'\n option enabled '0'\n option domain 'fixture.example.net'\n option lookup_host 'fixture.example.net'\n option username 'synthetic-user'\n option password 'synthetic-only'\n option ip_source 'network'\n")
    actual_uci="""local u=require('uci').cursor(arg[1],arg[2]);local m=assert(loadfile(arg[3]))();assert(m.apply(u)==1);u:unload('ddns');assert(u:get('ddns','fixture','password')=='synthetic-only');assert(u:get('ddns','fixture','username')=='synthetic-user');assert(u:get('ddns','fixture','enabled')=='0');assert(u:get('ddns','fixture','domain')=='fixture.example.net');assert(u:get('ddns','fixture','use_https')=='1');assert(u:get('ddns','fixture','ip_source')=='web');assert(u:get('ddns','global','use_curl')=='1');assert(m.apply(u)==0);print('PASS real ARM64 UCI retained credentials and committed migration')"""
    uci_fixture=td/'uci-test.lua';uci_fixture.write_text(actual_uci)
    check('real UCI preservation',lua+[str(uci_fixture),str(conf),str(saved),str(source/'usr/lib/lua/cudy/dynu-migrate.lua')],True)
    stub=td/'resolver';stub.write_text('#!/bin/sh\nif [ "$1" = --public-ip ]; then [ "$2" = 114.246.103.22 ]; else printf "%s\\n" 162.216.242.28 162.216.242.58; fi\n');stub.chmod(0o755)
    provider=td/'provider';provider.write_text((source/'usr/lib/ddns/update_cudy_dynu_https.sh').read_text().replace('/usr/libexec/cudy-dynu-resolve',str(stub)))
    harness=r'''set -u
write_log() { :; }
do_transfer() {
 calls=$((calls+1))
 case "$CURL" in *'--resolve api.dynu.com:443:162.216.242.'*) :;; *) return 1;; esac
 case "$1" in 'https://api.dynu.com/nic/update?hostname=fixture.example.net&myip=114.246.103.22&myipv6=no&username=fixture-user&password=fixture-only') :;; *) return 1;; esac
 [ "$scenario" = fallback ] && [ "$calls" = 1 ] && return 1
 [ "$scenario" = transport ] && return 1
 case "$scenario" in good|fallback) printf 'good 114.246.103.22\n' > "$DATFILE";; nochg) printf 'nochg 114.246.103.22\n' > "$DATFILE";; badauth) printf 'badauth\n' > "$DATFILE";; *) printf '<html>error</html>\n' > "$DATFILE";; esac
 return 0
}
invoke_provider() { . '@PROVIDER@'; }
run_case() {
 local scenario="$1" want="$2" wantcalls="$3" calls=0 actual=0
 local CURL=/usr/bin/curl URL_USER=fixture-user URL_PASS=fixture-only domain=fixture.example.net
 local use_https=1 use_ipv6=0 __IP=114.246.103.22 DATFILE='@DATA@'
 [ "$scenario" = nohttps ] && use_https=0
 [ "$scenario" = private ] && __IP=192.168.0.101
 if invoke_provider; then actual=0; else actual=1; fi
 [ "$actual" = "$want" ] && [ "$calls" = "$wantcalls" ] || { printf 'FAIL:%s\n' "$scenario"; exit 1; }
 printf 'PASS provider: %s\n' "$scenario"
}
run_case good 0 1
run_case nochg 0 1
run_case badauth 1 1
run_case malformed 1 1
run_case fallback 0 2
run_case transport 1 2
run_case nohttps 1 0
run_case private 1 0
'''.replace('@PROVIDER@',str(provider)).replace('@DATA@',str(td/'response'))
    p=td/'harness';p.write_text(harness)
    log=check('BusyBox provider contract',['qemu-aarch64-static','-L',str(root),str(root/'bin/busybox'),'sh',str(p)],True)
    assert log.count('PASS provider: ')==8;print(log,end='')
print(json.dumps({'DDNS_HTTPS_regressions_passed':True,'resolver_cases':7,'provider_cases':8,'migration_cases':10,'runtime':'actual ARM64 Lua/jsonc/UCI/BusyBox; synthetic fixtures only'}))
