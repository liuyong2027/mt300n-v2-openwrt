#!/usr/bin/env python3
"""Run the real first-boot script against isolated owner/fresh UCI fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('defaults',ROOT/'tr3600/zt-firewall-defaults.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
SOURCE=(ROOT/'tr3600/fixtures/mango-firewall-95-original.sh').read_text()

class Defaults(unittest.TestCase):
    def test_locked_source(self):
        self.assertIn('set firewall.mango_zt.forward=\'ACCEPT\'',mod.patch(SOURCE))
        with self.assertRaises(AssertionError): mod.patch(SOURCE+'\n')

    @unittest.skipIf(os.name=='nt','POSIX UCI fixture executes in CI')
    def test_fresh_defaults_and_owner_upgrade(self):
        (ROOT/'reports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='zt-policy-defaults-',dir=ROOT/'reports') as td:
            base=Path(td);bindir=base/'bin';bindir.mkdir();(base/'rc.d').mkdir()
            state=base/'state.json';state.write_text('{}')
            uci=bindir/'uci'
            uci.write_text('''#!/usr/bin/env python3
import json,os,shlex,sys
from pathlib import Path
p=Path(os.environ['ZT_POLICY_FIXTURE']);d=json.loads(p.read_text());a=[x for x in sys.argv[1:] if x!='-q']
if a[0]=='get':
 if a[1] not in d: raise SystemExit(1)
 v=d[a[1]]; print(' '.join(v) if isinstance(v,list) else v)
elif a[0]=='batch':
 for line in sys.stdin:
  v=shlex.split(line)
  if not v or v[0]=='commit': continue
  if v[0] in ('set','add_list'):
   k,value=v[1].split('=',1)
   if v[0]=='set': d[k]=value
   else: d.setdefault(k,[]).append(value)
  elif v[0]=='delete': d.pop(v[1],None)
  else: raise SystemExit('Unexpected fixture command')
 p.write_text(json.dumps(d))
elif a[0]!='commit': raise SystemExit(2)
''');uci.chmod(0o755)
            for service in ('xray','mango_proxy','mango_watchdog'):
                p=bindir/service;p.write_text('#!/bin/sh\nexit 0\n');p.chmod(0o755)
            script=base/'defaults.sh'
            script.write_text(mod.patch(SOURCE).replace('/etc/init.d/',str(bindir)+'/').replace('/etc/rc.d/',str(base/'rc.d')+'/'))
            env=dict(os.environ,PATH=str(bindir)+os.pathsep+os.environ['PATH'],ZT_POLICY_FIXTURE=str(state))
            subprocess.run(['sh',str(script)],env=env,check=True)
            fresh=json.loads(state.read_text())
            self.assertEqual([fresh['firewall.mango_zt.'+k] for k in ('input','output','forward','masq')],['ACCEPT','ACCEPT','ACCEPT','1'])
            self.assertEqual(fresh['firewall.mango_zt.device'],['zt+'])
            before=state.read_bytes();subprocess.run(['sh',str(script)],env=env,check=True)
            self.assertEqual(state.read_bytes(),before)
            fresh.update({'firewall.mango_zt.forward':'REJECT','firewall.mango_zt.masq':'0','firewall.mango_zt.masq_src':['10.20.30.0/24'],'firewall.mango_zt_dns.enabled':'0','firewall.mango_zt_dns.src_ip':'10.20.40.0/24','firewall.mango_zt_wan.enabled':'0','firewall.mango_proxy.path':'/owner/custom-fw','firewall.customer':'rule','firewall.customer.target':'DROP'})
            state.write_text(json.dumps(fresh));before=state.read_bytes()
            subprocess.run(['sh',str(script)],env=env,check=True)
            self.assertEqual(state.read_bytes(),before,'Owner policies, NAT scope, disabled services and unrelated rules must survive')
            del fresh['firewall.mango_mark'];fresh={k:v for k,v in fresh.items() if not k.startswith('firewall.mango_mark.')}
            state.write_text(json.dumps(fresh));subprocess.run(['sh',str(script)],env=env,check=True)
            after=json.loads(state.read_text());self.assertEqual(after['firewall.mango_mark'],'rule')
            self.assertEqual(after['firewall.mango_zt.forward'],'REJECT');self.assertEqual(after['firewall.mango_zt.masq_src'],['10.20.30.0/24'])

if __name__=='__main__': unittest.main()
