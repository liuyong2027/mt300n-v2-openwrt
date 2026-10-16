#!/usr/bin/env python3
"""Regression checks for exact upstream hooks and upgrade preservation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('zt',ROOT/'tr3600/zt-integration.py')
zt=importlib.util.module_from_spec(spec);spec.loader.exec_module(zt)
source=(ROOT/'tr3600/fixtures/zerotier-5caa62e0.init').read_text()
script=(ROOT/'tr3600/network-root/etc/uci-defaults/96-cudy-zt-direct').read_text()

class Integration(unittest.TestCase):
    def test_locked_hooks(self):
        patched=zt.patch(source)
        self.assertEqual(patched.count('/usr/libexec/cudy-zt-direct ||'),2)
        self.assertIn('procd_add_reload_trigger \'zerotier\'',patched)
        with self.assertRaises(AssertionError): zt.patch(source+'\n')

    def test_keep_path_and_no_probe_daemon(self):
        keep=ROOT/'tr3600/network-root/lib/upgrade/keep.d/cudy-zt-direct'
        self.assertEqual(keep.read_text().strip(),'/etc/zerotier-stable-ports.json')
        run=(ROOT/'tr3600/network-root/usr/libexec/cudy-zt-direct-run').read_text()
        self.assertNotIn('192.168.0.1',run)
        self.assertNotIn('ping ',run)
        self.assertNotIn('/etc/init.d/mango',run)

    @unittest.skipIf(os.name=='nt','POSIX first-boot fixtures run in CI')
    def test_first_boot_preserves_existing_configuration(self):
        (ROOT/'reports').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='zt-firstboot-',dir=ROOT/'reports') as td:
            base=Path(td); bindir=base/'bin';bindir.mkdir()
            state=base/'uci.json';stable=base/'stable.json'
            uci=bindir/'uci'
            uci.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['ZT_FIXTURE']);d=json.loads(p.read_text())
a=[x for x in sys.argv[1:] if x!='-q']
if a[0]=='get':
 if a[1] not in d: raise SystemExit(1)
 print(d[a[1]])
elif a[0]=='set':
 k,v=a[1].split('=',1);d[k]=v;p.write_text(json.dumps(d))
elif a[0]!='commit': raise SystemExit(2)
''');uci.chmod(0o755)
            # board-only cat mock; all remaining writes stay in the fixture.
            cat=bindir/'cat';cat.write_text("#!/bin/sh\nprintf '%s\\n' 'cudy,tr3600-v1'\n");cat.chmod(0o755)
            logger=bindir/'logger';logger.write_text('#!/bin/sh\nexit 0\n');logger.chmod(0o755)
            local=base/'setup.sh';local.write_text(script.replace('/etc/zerotier-stable-ports.json',str(stable)))
            env=dict(os.environ,PATH=str(bindir)+os.pathsep+os.environ['PATH'],ZT_FIXTURE=str(state))
            state.write_text(json.dumps({'zerotier.global.enabled':'0','zerotier.global.secret':'fixture-identity-keep'}))
            subprocess.run(['sh',str(local)],env=env,check=True)
            self.assertEqual(json.loads(stable.read_text())['settings']['tertiaryPort'],20089)
            d=json.loads(state.read_text());self.assertEqual(d['zerotier.global.enabled'],'0')
            self.assertEqual(d['zerotier.global.secret'],'fixture-identity-keep')
            self.assertEqual(d['zerotier.global.local_conf_path'],str(stable))
            owner=b'{"settings":{"secondaryPort":34567,"tertiaryPort":45678,"portMappingEnabled":false}}\n'
            stable.write_bytes(owner)
            subprocess.run(['sh',str(local)],env=env,check=True)
            self.assertEqual(stable.read_bytes(),owner)
            d['zerotier.global.local_conf_path']='/etc/custom-owner.conf';state.write_text(json.dumps(d))
            subprocess.run(['sh',str(local)],env=env,check=True)
            self.assertEqual(json.loads(state.read_text())['zerotier.global.local_conf_path'],'/etc/custom-owner.conf')
            self.assertEqual(stable.read_bytes(),owner)
            d=json.loads(state.read_text());d['firewall.cudy_zt_direct.path']='/owner/include';state.write_text(json.dumps(d))
            self.assertNotEqual(subprocess.run(['sh',str(local)],env=env).returncode,0)
            self.assertEqual(json.loads(state.read_text())['firewall.cudy_zt_direct.path'],'/owner/include')

if __name__=='__main__': unittest.main()
