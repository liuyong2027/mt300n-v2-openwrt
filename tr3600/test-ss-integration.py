#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
kit=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ss',Path(__file__).with_name('ss-integration.py'))
ss=importlib.util.module_from_spec(spec);spec.loader.exec_module(ss)
class Integration(unittest.TestCase):
    def test_exact_original_backups_and_narrow_init_hook(self):
        reports=kit/'reports';reports.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=reports,prefix='ss-integration-') as temp:
            assert Path(temp).resolve().is_relative_to(reports.resolve())
            root=Path(temp)/'package/luci-app-mango-proxy/root'
            original=kit/'package/luci-app-mango-proxy/root'
            shutil.copytree(original,root)
            ss.install(temp)
            for name,wrapper in ss.WRAPPERS.items():
                self.assertEqual((root/name).read_text(encoding='utf-8'),wrapper)
                self.assertEqual((root/(name+'.cudy-ss-base')).read_bytes(),(original/name).read_bytes())
            self.assertEqual((root/'etc/init.d/mango_proxy').read_text(encoding='utf-8'),ss.patch_init((original/'etc/init.d/mango_proxy').read_text(encoding='utf-8')))
            with self.assertRaises(AssertionError): ss.install(temp)
    def test_unknown_init_rejected(self):
        with self.assertRaises(AssertionError): ss.patch_init('unrecognized core')
        with self.assertRaises(AssertionError): ss.patch_init('cudy_ss.main.enabled')
    def test_disabled_image_has_no_user_secrets_and_narrow_acl(self):
        root=kit/'tr3600/luci-app-cudy-ss/root'
        data=(root/'etc/config/cudy_ss').read_text()
        self.assertIn("option enabled '0'",data)
        for field in ('password','listen','subnet','network_id','interface'):
            self.assertNotIn('option '+field,data)
        acl=json.loads((root/'usr/share/rpcd/acl.d/luci-app-cudy-ss.json').read_text())['luci-app-cudy-ss']
        self.assertEqual(acl['read'],{'ubus':{'cudy.ss':['status']}})
        self.assertEqual(acl['write'],{'ubus':{'cudy.ss':['configure','client']}})
        self.assertNotIn('option network_id',data)
if __name__=='__main__': unittest.main()
