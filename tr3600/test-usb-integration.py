#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

kit=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('usb_integration',kit/'tr3600/usb-integration.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
stock=(kit/'tr3600/fixtures/samba-5caa62e0.init').read_text(encoding='utf-8')

class Integration(unittest.TestCase):
    def test_pinned_source_and_reject_unknown(self):
        patched=module.patch_text(stock)
        self.assertIn('cudy-usb guard %s %s',patched)
        self.assertIn('xattr_tdb:file = %s/.samba-metadata/xattr.tdb',patched)
        with self.assertRaises(AssertionError): module.patch_text(stock+'# unexpected\n')
    def test_luci_acl_separates_status_from_mutation(self):
        root=kit/'tr3600/luci-app-cudy-usb/root'
        acl=json.loads((root/'usr/share/rpcd/acl.d/luci-app-cudy-usb.json').read_text())['luci-app-cudy-usb']
        self.assertEqual(acl['read']['file'],{'/usr/libexec/cudy-usb status':['exec']})
        self.assertNotIn('uci',acl['write'])
        self.assertEqual(set(acl['write']['file']),{'/usr/libexec/cudy-usb enable *','/usr/libexec/cudy-usb eject *','/usr/libexec/cudy-usb forget *'})
    @unittest.skipUnless(shutil.which('sh') and shutil.which('testparm'), 'Linux sh and Samba testparm required')
    def test_generated_shares_use_per_volume_guard_and_metadata(self):
        with tempfile.TemporaryDirectory(prefix='cudy-samba-test-') as temp:
            target=Path(temp)/'smb.conf';target.write_text('[global]\n security = user\n map to guest = Bad User\n')
            init=module.patch_text(stock).replace('/var/etc/smb.conf',str(target))
            script=Path(temp)/'run.sh'
            script.write_text(init+'\n'+r'''
config_get() {
  eval "v=\${CFG_${2}_${3}-}"
  [ -n "$v" ] || v="${4-}"
  eval "$1=\$v"
}
config_get_bool() { config_get "$@"; }
MACOS=1; DISABLE_ASYNC_IO=1
CFG_regular_name=Documents; CFG_regular_path=/mnt/documents
smb_add_share regular
CFG_usb_abcd_1234_name=USB; CFG_usb_abcd_1234_path=/mnt/cudy-usb/usb_abcd_1234
CFG_usb_abcd_1234_read_only=no; CFG_usb_abcd_1234_cudy_usb=usb_abcd_1234
smb_add_share usb_abcd_1234
CFG_usb_5678_1234_name=ReadOnly; CFG_usb_5678_1234_path=/mnt/cudy-usb/usb_5678_1234
CFG_usb_5678_1234_read_only=yes; CFG_usb_5678_1234_cudy_usb=usb_5678_1234
smb_add_share usb_5678_1234
CFG_usb_bad_name=Invalid; CFG_usb_bad_path=/root; CFG_usb_bad_cudy_usb=usb_bad
smb_add_share usb_bad
''',encoding='utf-8')
            subprocess.run(['sh',str(script)],check=True)
            def section(name):
                result=subprocess.run(['testparm','-s','--section-name='+name,str(target)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,check=True)
                return result.stdout
            usb=section('USB');ro=section('ReadOnly');regular=section('Documents');invalid=section('Invalid')
            self.assertIn('root preexec = /usr/libexec/cudy-usb guard usb_abcd_1234 /mnt/cudy-usb/usb_abcd_1234',usb)
            self.assertIn('root preexec close = Yes',usb)
            self.assertIn('xattr_tdb:file = /mnt/cudy-usb/usb_abcd_1234/.samba-metadata/xattr.tdb',usb)
            self.assertIn('vfs objects = catia fruit streams_xattr xattr_tdb',usb)
            self.assertNotIn('xattr_tdb',ro)
            self.assertNotIn('root preexec',regular)
            self.assertIn('root preexec = /bin/false',invalid)

if __name__=='__main__': unittest.main(verbosity=2)
