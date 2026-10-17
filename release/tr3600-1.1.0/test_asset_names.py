#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from asset_names import version_image

class AssetNames(unittest.TestCase):
    def fixture(self, root):
        data = b'disposable-sysupgrade-container-fixture'
        original = root / 'openwrt-mediatek-filogic-cudy_tr3600-v1-squashfs-sysupgrade.bin'
        original.write_bytes(data)
        proof = {'device':'cudy,tr3600-v1','version':'tr3600-1.1.0','image':original.name,'image_sha256':hashlib.sha256(data).hexdigest(),'source_commit':'1'*40,'hardware_validation':'pending'}
        (root/'tr3600-verification.json').write_text(json.dumps(proof))
        return original, data, proof

    def test_published_name_and_report_match_without_changing_payload(self):
        with tempfile.TemporaryDirectory(prefix='tr3600-asset-name-') as directory:
            root = Path(directory)
            original, data, proof = self.fixture(root)
            target = version_image(root, '1.1.0')
            self.assertEqual(target.name, 'cudy-tr3600-v1-1.1.0-sysupgrade.bin')
            self.assertFalse(original.exists())
            self.assertEqual(target.read_bytes(), data)
            actual = json.loads((root/'tr3600-verification.json').read_text())
            self.assertEqual(actual['image'], target.name)
            self.assertEqual(actual['image_sha256'], proof['image_sha256'])
            self.assertEqual(actual['source_commit'], proof['source_commit'])
            self.assertEqual(actual['hardware_validation'], 'pending')
            self.assertEqual(version_image(root, '1.1.0'), target)

    def test_changed_payload_is_rejected_before_renaming(self):
        with tempfile.TemporaryDirectory(prefix='tr3600-asset-name-') as directory:
            root = Path(directory)
            original, _, _ = self.fixture(root)
            original.write_bytes(b'changed-fixture')
            with self.assertRaises(AssertionError):
                version_image(root, '1.1.0')
            self.assertTrue(original.exists())

    def test_existing_versioned_asset_is_not_overwritten(self):
        with tempfile.TemporaryDirectory(prefix='tr3600-asset-name-') as directory:
            root = Path(directory)
            original, _, _ = self.fixture(root)
            collision = root / 'cudy-tr3600-v1-1.1.0-sysupgrade.bin'
            collision.write_bytes(b'existing-owner-asset')
            with self.assertRaises(AssertionError):
                version_image(root, '1.1.0')
            self.assertEqual(collision.read_bytes(), b'existing-owner-asset')
            self.assertTrue(original.exists())

    def test_different_device_or_version_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='tr3600-asset-name-') as directory:
            root = Path(directory)
            original, _, proof = self.fixture(root)
            with self.assertRaises(AssertionError):
                version_image(root, '99.0.0-rc1')
            proof['device'] = 'other-device'
            (root/'tr3600-verification.json').write_text(json.dumps(proof))
            with self.assertRaises(AssertionError):
                version_image(root, '1.1.0')
            self.assertTrue(original.exists())

if __name__ == '__main__':
    unittest.main(verbosity=2)
