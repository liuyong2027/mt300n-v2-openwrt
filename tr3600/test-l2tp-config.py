#!/usr/bin/env python3
"""Exercise configuration validation without reading real router credentials."""
import json
from pathlib import Path
import subprocess
import tempfile

kit = Path(__file__).resolve().parent
generator = kit/'luci-app-cudy-l2tp/root/usr/libexec/cudy-l2tp-config'
valid = dict(enabled='1', username='vpnuser', password='TestPass_12345',
             psk='TestPSK_123456', subnet='192.168.89', dns='192.168.8.1')

def literal(value):
    if isinstance(value, dict):
        return '{'+','.join('['+literal(k)+']='+literal(v) for k,v in value.items())+'}'
    if isinstance(value, list):
        return '{'+','.join(literal(v) for v in value)+'}'
    return json.dumps(value)

def run(config, networks=(), expected=0):
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        runner = out/'fixture.lua'
        runner.write_text('local c='+literal(config)+'\nlocal nets='+literal(list(networks))+'''
package.preload.uci = function()
  return {cursor=function() return {
    get_all=function() return c end,
    foreach=function(self, config, kind, cb) for _, n in ipairs(nets) do cb(n) end end
  } end}
end
arg = {'''+literal(str(out))+'''}
dofile('''+literal(str(generator))+')\n')
        p = subprocess.run(['lua5.1',str(runner)],capture_output=True,text=True)
        assert p.returncode == expected, (config,networks,p.returncode,p.stderr)
        assert config.get('password','NO_SECRET') not in p.stdout+p.stderr
        assert config.get('psk','NO_SECRET') not in p.stdout+p.stderr
        files = {f.name:f.read_text() for f in out.iterdir() if f.name != 'fixture.lua'}
        if expected:
            assert not files, files
        return files

files = run(valid,[dict(ipaddr='192.168.8.1',netmask='255.255.255.0')])
assert set(files) == {'strongswan.conf','swanctl.conf','chap-secrets','ppp.options','xl2tpd.conf'}
assert 'version = 1' in files['swanctl.conf'] and 'mode = transport' in files['swanctl.conf']
assert 'local_ts = dynamic[udp/1701]' in files['swanctl.conf']
assert 'require-mschap-v2' in files['ppp.options']
assert 'ifname l2tpvpn' in files['ppp.options']
assert 'chap-secrets /var/run/cudy-l2tp/chap-secrets' in files['ppp.options']
assert '192.168.89.10-192.168.89.19' in files['xl2tpd.conf']
assert 'TestPass_12345' in files['chap-secrets'] and 'TestPSK_123456' in files['swanctl.conf']
run(dict(valid,enabled='0'),expected=2)
for field,value in [('password','short'),('psk','x"\nremote { auth = pubkey }'),
                    ('username','bad user'),('username','x\ny'),('subnet','192.168.999'),
                    ('subnet','8.8.8'),('dns','256.1.1.1')]:
    run(dict(valid,**{field:value}),expected=1)
run(valid,[dict(ipaddr='192.168.89.1/24')],expected=1)
run(valid,[dict(ipaddr='192.168.1.1',netmask='255.255.0.0')],expected=1)
run(valid,[dict(ipaddr=['192.168.8.1/24','192.168.89.99/32'])],expected=1)
run(dict(valid,subnet='10.90.90'),[dict(ipaddr='192.168.8.1/24')])
print('L2TP/IPsec generation, credentials, subnet overlap and disabled-state checks passed')

