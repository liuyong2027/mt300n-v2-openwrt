#!/usr/bin/env python3
"""Check consent defaults and preservation of encrypted account/TLS fixtures."""
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / 'tr3600/cudy-webfiles'

class WebFilesIntegration(unittest.TestCase):
    def test_clean_defaults_require_owner_volume_and_access_selection(self):
        text = (CORE / 'root/etc/config/cudy_webfiles').read_text()
        for option in ("enabled '0'", "volume ''", "read_write '0'", "zerotier '0'", "public_enabled '0'"):
            self.assertIn('option ' + option, text)
        self.assertNotIn('usb_2ac7_e8ef', text)
        source = (ROOT / 'tr3600/webfiles/helper/managed_linux.go').read_text(encoding='utf-8')
        self.assertIn('uciGet("volume", "")', source)
        self.assertNotIn('uciGet("volume", "usb_2ac7_e8ef")', source)

    def test_sysupgrade_keep_list_preserves_encryption_key_accounts_and_all_TLS_slots(self):
        paths = (CORE / 'root/lib/upgrade/keep.d/cudy-webfiles').read_text().splitlines()
        self.assertIn('/etc/config/cudy_webfiles', paths)
        self.assertIn('/etc/cudy-webfiles/', paths)
        fixture_names = ('marker', 'account.key', 'account.enc', 'accounts.enc', 'tls.enc', 'public-tls.enc', 'public-domain-tls.enc')
        reports = ROOT / 'reports'
        reports.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='webfiles-keep-', dir=reports) as directory:
            self.assertEqual(Path(directory).resolve().parent, reports.resolve())
            root = Path(directory)
            for name in fixture_names:
                target = root / 'etc/cudy-webfiles' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(('synthetic-private-fixture:' + name).encode())
            config = root / 'etc/config/cudy_webfiles'
            config.parent.mkdir(parents=True)
            config.write_text("config webfiles 'main'\n option port '8080'\n")
            selected = set()
            for path in paths:
                target = root / path.lstrip('/')
                if target.is_dir(): selected.update(p for p in target.rglob('*') if p.is_file())
                elif target.is_file(): selected.add(target)
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode='w:gz') as archive:
                for path in selected: archive.add(path, arcname=path.relative_to(root))
            data.seek(0)
            with tarfile.open(fileobj=data) as archive:
                expected = {'etc/cudy-webfiles/' + name for name in fixture_names} | {'etc/config/cudy_webfiles'}
                self.assertEqual(set(archive.getnames()), expected)
                for name in expected:
                    self.assertEqual(archive.extractfile(name).read(), (root / name).read_bytes())

    def test_startup_follows_USB_and_preserves_guard_failure_behavior(self):
        init = (CORE / 'root/etc/init.d/cudy-webfiles').read_text()
        self.assertIn('START=99', init)
        self.assertIn('START=97', (ROOT / 'tr3600/luci-app-cudy-usb/root/etc/init.d/cudy_usb').read_text())
        self.assertNotIn('procd_set_param respawn', init)
        self.assertNotIn('usb_2ac7_e8ef', init)
        self.assertIn('"$helper" boot-run', init)
        self.assertIn('procd_set_param stderr 1', init)

if __name__ == '__main__':
    unittest.main(verbosity=2)
