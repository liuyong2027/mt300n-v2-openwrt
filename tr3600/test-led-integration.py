#!/usr/bin/env python3
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

kit=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
led=module('led_integration',kit/'tr3600/led-integration.py')

class Integration(unittest.TestCase):
    def test_additive_probe_is_based_on_verified_original(self):
        original=(kit/'package/luci-app-mango-proxy/root/usr/libexec/mango-probe').read_bytes()
        digest=json.loads((kit/'VALIDATION-20.json').read_text())['source_rootfs_sha256']['usr/libexec/mango-probe']
        self.assertEqual(hashlib.sha256(original).hexdigest(),digest)
        patched=led.patch_probe(original.decode())
        self.assertEqual(patched.count('/usr/libexec/timeout-coreutils 2 /usr/libexec/cudy-led-control'),3)
        self.assertIn('|| :; write_log ok || :; exit 0',patched)
        self.assertIn('|| :; write_log failed || :\nexit 1',patched)
        reversed=patched.replace('cudy_led_token=$(/usr/libexec/timeout-coreutils 2 /usr/libexec/cudy-led-control begin 2>/dev/null) || cudy_led_token=\n','')
        for code in ('0','1'):
            reversed=reversed.replace('/usr/libexec/timeout-coreutils 2 /usr/libexec/cudy-led-control finish "$cudy_led_token" '+code+' >/dev/null 2>&1 || :; ','')
        self.assertEqual(reversed.encode(),original)
        with self.assertRaises(AssertionError): led.patch_probe(patched)
    def test_upgrade_handoff_after_validation_and_test_exit(self):
        original='if [ $TEST -eq 1 ]; then\n\texit 0\nfi\ninstall_bin /sbin/upgraded\nv "Commencing upgrade. Closing all shell sessions."\nif [ -n "$FAILSAFE" ]; then\n :\nelse\n\tubus call system sysupgrade "$(json_dump)"\nfi\n'
        patched=led.patch_upgrade(original)
        self.assertGreater(patched.index('cudy-led-upgrade suspend'),patched.index('install_bin /sbin/upgraded'))
        self.assertGreater(patched.index('cudy-led-upgrade resume'),patched.index('ubus call system sysupgrade'))
        self.assertIn('if [ "$cudy_led_result" != 0 ]; then',patched)
        self.assertIn('exit "$cudy_led_result"',patched)
        with self.assertRaises(AssertionError): led.patch_upgrade(patched)
    def test_full_recipe_adaptation_from_original_bundle(self):
        port=module('tr3600_port',kit/'tr3600/port.py')
        parent=kit/'reports'; parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='cudy-led-recipe-',dir=parent) as temp:
            root=Path(temp)
            assert root.resolve().is_relative_to(parent.resolve())
            shutil.copyfile(kit/'release20-test-failover1-source.zip.b64',root/'release20-test-failover1-source.zip.b64')
            shutil.copytree(kit/'tr3600',root/'tr3600')
            port.ROOT=root; port.extract(); port.adapt()
            s=(root/'scripts/prepare.sh').read_text()
            self.assertIn('cp -R "$kit/tr3600/luci-app-cudy-led" package/',s)
            self.assertIn('python3 "$kit/tr3600/led-integration.py" "$PWD"',s)
            self.assertLess(s.index('cp -R "$kit/package/luci-app-mango-proxy"'),s.index('led-integration.py'))
            self.assertLess(s.index('led-integration.py'),s.index('make defconfig'))
            features=json.loads((root/'reports/tr3600-source.json').read_text())['requested_features']
            self.assertTrue(any('White/red network and proxy status LEDs' in feature for feature in features))
    def test_acl_and_defaults(self):
        root=kit/'tr3600/luci-app-cudy-led/root'
        acl=json.loads((root/'usr/share/rpcd/acl.d/luci-app-cudy-led.json').read_text())['luci-app-cudy-led']
        self.assertEqual(acl['write']['uci'],['cudy_led'])
        self.assertEqual(acl['write']['file'],{'/usr/libexec/cudy-led-apply':['exec']})
        menu=json.loads((root/'usr/share/luci/menu.d/luci-app-cudy-led.json').read_text(encoding='utf-8'))
        self.assertEqual(menu['admin/system/cudy-led']['action']['path'],'cudy-led')
        self.assertIn("option mode 'status'",(root/'etc/config/cudy_led').read_text())
        self.assertIn("option night '0'",(root/'etc/config/cudy_led').read_text())

if __name__=='__main__': unittest.main(verbosity=2)
