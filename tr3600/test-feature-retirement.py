#!/usr/bin/env python3
"""Exercise retired-feature absence and reversible upgrade cleanup in fixtures."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

kit = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('removed', kit/'tr3600/check-removed.py')
removed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(removed)
script = (kit/'tr3600/network-root/etc/uci-defaults/91-cudy-retire-services').read_text()
sections = ('cudy_l2tp_ike', 'cudy_l2tp_esp', 'cudy_l2tp_zone', 'cudy_l2tp_lan', 'cudy_l2tp_wan', 'cudy_l2tp_zt')

class Retirement(unittest.TestCase):
    def setUp(self):
        (kit/'reports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='cudy-retirement-', dir=kit/'reports')
        self.root = Path(self.temp.name)
        for name in ('etc/config', 'etc/rc.d', 'root', 'tmp/sysinfo', 'bin'):
            (self.root/name).mkdir(parents=True)
        (self.root/'tmp/sysinfo/board_name').write_text('cudy,tr3600-v1\n')
        firewall = "config zone 'lan'\n\toption name 'lan'\n\nconfig rule 'custom_keep'\n\toption target 'REJECT'\n"
        for section in sections:
            firewall += "\nconfig rule '%s'\n\toption enabled '1'\n" % section
        (self.root/'etc/config/firewall').write_text(firewall)
        self.original = firewall
        for name in ('cudy_l2tp', 'ddns'):
            (self.root/'etc/config'/name).write_text('fixture-only-private-config\n')
        for name in ('cudy_l2tp', 'xl2tpd', 'swanctl', 'ddns', 'mango_proxy', 'samba4'):
            (self.root/'etc/rc.d'/('S95'+name)).symlink_to('../init.d/'+name)
        # During ARM64 CI use the actual compiled UCI parser. Early host tests
        # use a small fixture command to test backup/failure/order behavior.
        wrapper = self.root/'bin/uci'
        wrapper.write_text('''#!/usr/bin/env python3
import os, re, subprocess, sys
from pathlib import Path
root=Path(os.environ['CUDY_RETIRE_FIXTURE'])
actual=os.environ.get('CUDY_TEST_ROOT')
if actual:
    command=['qemu-aarch64-static','-L',actual,actual+'/sbin/uci','-c',str(root/'etc/config')]+sys.argv[1:]
    raise SystemExit(subprocess.run(command).returncode)
args=[a for a in sys.argv[1:] if a!='-q']
path=root/'etc/config/firewall'; data=path.read_text()
if args[0]=='commit': raise SystemExit(0)
section=args[1].split('.',1)[1]
pattern=r"(?m)^config [^\\n]+ '"+re.escape(section)+r"'\\n(?:[ \\t][^\\n]*\\n|\\n)*"
match=re.search(pattern,data)
if not match: raise SystemExit(1)
if args[0]=='get': print('rule')
elif args[0]=='delete': path.write_text(data[:match.start()]+data[match.end():])
else: raise SystemExit(2)
''')
        wrapper.chmod(0o755)
        self.runner = self.root/'run.sh'
        text = script.replace('/tmp/sysinfo/', str(self.root/'tmp/sysinfo')+'/')
        text = text.replace('/root/', str(self.root/'root')+'/').replace('/etc/', str(self.root/'etc')+'/')
        self.runner.write_text(text)
        self.env = dict(os.environ, PATH=str(self.root/'bin')+os.pathsep+os.environ['PATH'], CUDY_RETIRE_FIXTURE=str(self.root))
    def tearDown(self): self.temp.cleanup()
    def run_script(self): return subprocess.run(['sh', str(self.runner)], env=self.env, capture_output=True, text=True)
    def test_upgrade_backup_private_and_only_owned_sections_removed(self):
        result=self.run_script(); self.assertEqual(result.returncode,0,result.stderr)
        data=(self.root/'etc/config/firewall').read_text()
        for section in sections: self.assertNotIn(section,data)
        self.assertIn('custom_keep',data); self.assertIn('REJECT',data); self.assertIn('lan',data)
        backup=self.root/'root/.cudy-retired-test2'
        self.assertEqual(backup.stat().st_mode & 0o777,0o700)
        self.assertEqual((backup/'firewall').read_text(),self.original)
        for name in ('firewall','cudy_l2tp','ddns'): self.assertEqual((backup/name).stat().st_mode & 0o777,0o600)
        for name in ('cudy_l2tp','ddns'): self.assertFalse((self.root/'etc/config'/name).exists())
        for name in ('cudy_l2tp','xl2tpd','swanctl','ddns'): self.assertFalse((self.root/'etc/rc.d'/('S95'+name)).is_symlink())
        for name in ('mango_proxy','samba4'): self.assertTrue((self.root/'etc/rc.d'/('S95'+name)).is_symlink())
        self.assertEqual(self.run_script().returncode,0)
        self.assertEqual((backup/'firewall').read_text(),self.original)
    def test_wrong_board_changes_nothing(self):
        (self.root/'tmp/sysinfo/board_name').write_text('other,device\n')
        self.assertEqual(self.run_script().returncode,0)
        self.assertEqual((self.root/'etc/config/firewall').read_text(),self.original)
        self.assertTrue((self.root/'etc/config/ddns').exists())
        self.assertFalse((self.root/'root/.cudy-retired-test2').exists())
    def test_backup_failure_keeps_original_configuration(self):
        (self.root/'root/.cudy-retired-test2').write_text('occupied')
        self.assertNotEqual(self.run_script().returncode,0)
        self.assertEqual((self.root/'etc/config/firewall').read_text(),self.original)
        self.assertTrue((self.root/'etc/config/ddns').exists())
    def test_clean_install_does_not_create_private_backup(self):
        for name in ('cudy_l2tp','ddns'): (self.root/'etc/config'/name).unlink()
        (self.root/'etc/config/firewall').write_text("config zone 'lan'\n\toption name 'lan'\n")
        self.assertEqual(self.run_script().returncode,0)
        self.assertFalse((self.root/'root/.cudy-retired-test2').exists())
    def test_absence_audit_rejects_removed_content_and_package(self):
        image=self.root/'image'; image.mkdir()
        removed.validate_root(image)
        for path in ('etc/init.d/ddns','usr/sbin/xl2tpd','www/luci-static/resources/view/cudy-l2tp.js'):
            target=image/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text('unexpected')
            with self.assertRaises(AssertionError): removed.validate_root(image)
            target.unlink()
        config=self.root/'image.config'
        for name in ('strongswan-charon','ddns-scripts-dynu','luci-app-ddns','cudy-l2tp-ifname'):
            config.write_text('CONFIG_PACKAGE_'+name+'=y\n')
            with self.assertRaises(AssertionError): removed.validate_config(config)
        config.write_text('CONFIG_PACKAGE_ppp=y\nCONFIG_PACKAGE_zerotier=y\n')
        removed.validate_config(config)

if __name__ == '__main__': unittest.main(verbosity=2)
