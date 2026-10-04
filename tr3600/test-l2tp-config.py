#!/usr/bin/env python3
"""Exercise configuration validation without reading real router credentials."""
import json
from pathlib import Path
import subprocess
import tempfile

kit = Path(__file__).resolve().parent
generator = kit/'luci-app-cudy-l2tp/root/usr/libexec/cudy-l2tp-config'
valid = dict(enabled='1', psk='TestPSK_123456', subnet='192.168.89', dns='192.168.8.1')
valid_users = [dict(username='vpnuser',password='TestPass_12345'),
               dict(username='seconduser',password='SecondPass_1234')]

def literal(value):
    if isinstance(value, dict):
        return '{'+','.join('['+literal(k)+']='+literal(v) for k,v in value.items())+'}'
    if isinstance(value, list):
        return '{'+','.join(literal(v) for v in value)+'}'
    return json.dumps(value)

def run(config, networks=(), expected=0, users=None):
    users = valid_users if users is None else users
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        runner = out/'fixture.lua'
        runner.write_text('local c='+literal(config)+'\nlocal nets='+literal(list(networks))+'\nlocal users='+literal(users)+'''
package.preload.uci = function()
  return {cursor=function() return {
    get_all=function() return c end,
    foreach=function(self, config, kind, cb)
      local list = config == 'cudy_l2tp' and users or nets
      for _, n in ipairs(list) do cb(n) end
    end
  } end}
end
arg = {'''+literal(str(out))+'''}
dofile('''+literal(str(generator))+')\n')
        p = subprocess.run(['lua5.1',str(runner)],capture_output=True,text=True)
        assert p.returncode == expected, (config,networks,p.returncode,p.stderr)
        assert config.get('psk','NO_SECRET') not in p.stdout+p.stderr
        for user in users:
            assert user.get('password','NO_SECRET') not in p.stdout+p.stderr
        files = {f.name:f.read_text() for f in out.iterdir() if f.name != 'fixture.lua'}
        if expected:
            assert not files, files
        return files

files = run(valid,[dict(ipaddr='192.168.8.1',netmask='255.255.255.0')])
assert set(files) == {'strongswan.conf','swanctl.conf','chap-secrets','ppp.options','xl2tpd.conf'}
assert 'version = 1' in files['swanctl.conf'] and 'mode = transport' in files['swanctl.conf']
assert 'local_ts = dynamic[udp/1701]' in files['swanctl.conf']
assert 'require-mschap-v2' in files['ppp.options']
assert 'plugin /usr/lib/cudy-l2tp-ifname.so' in files['ppp.options']
assert 'chap-secrets /var/run/cudy-l2tp/chap-secrets' in files['ppp.options']
assert '192.168.89.10-192.168.89.99' in files['xl2tpd.conf']
assert 'TestPass_12345' in files['chap-secrets'] and 'TestPSK_123456' in files['swanctl.conf']
assert 'seconduser' in files['chap-secrets'] and len(files['chap-secrets'].splitlines()) == 2
run(dict(valid,enabled='0'),expected=2)
for field,value in [('psk','x"\nremote { auth = pubkey }'),('subnet','192.168.999'),
                    ('subnet','8.8.8'),('dns','256.1.1.1')]:
    run(dict(valid,**{field:value}),expected=1)
for field,value in [('password','short'),('username','bad user'),('username','x\ny')]:
    run(valid,expected=1,users=[dict(valid_users[0],**{field:value})])
run(valid,expected=1,users=[])
run(valid,expected=1,users=[valid_users[0],valid_users[0]])
run(valid,expected=1,users=[dict(username='user'+str(i),password='TestPass_12345') for i in range(33)])
files = run(valid,users=valid_users+[dict(username='disableduser',password='short',enabled='0')])
assert 'disableduser' not in files['chap-secrets']
run(valid,[dict(ipaddr='192.168.89.1/24')],expected=1)
run(valid,[dict(ipaddr='192.168.1.1',netmask='255.255.0.0')],expected=1)
run(valid,[dict(ipaddr=['192.168.8.1/24','192.168.89.99/32'])],expected=1)
run(dict(valid,subnet='10.90.90'),[dict(ipaddr='192.168.8.1/24')])
print('L2TP/IPsec multi-account generation, duplicate/disabled users, credentials and subnet validation passed')
