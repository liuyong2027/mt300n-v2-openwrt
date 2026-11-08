#!/usr/bin/env python3
"""Regress both reviewed generator layouts, defaults and fail-closed adaptation."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

kit = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_defaults', kit/'tr3600/network-defaults.py')
defaults = importlib.util.module_from_spec(spec)
spec.loader.exec_module(defaults)
path = Path('package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc')
INSERTIONS = (
    'const cudy_tr3600 = trim(readfile("/tmp/sysinfo/board_name") || "") == "cudy,tr3600-v1";\n\n',
    '\t\t// Existing radios are skipped below; never rewrite saved wireless settings.\n\t\tif (cudy_tr3600 && band_name == "5G" && band.he) {\n\t\t\tchannel = 36;\n\t\t\thtmode = "HE80";\n\t\t}\n\n',
)
SSID = '${defaults?.ssid || (cudy_tr3600 && band_name == "5g" ? "Cudy-TR3600-5G" : "OpenWrt")}'

def git_blob(data):
    blob = b'blob ' + str(len(data)).encode('ascii') + bytes([0]) + data
    return hashlib.sha1(blob).hexdigest()

def without_defaults(result):
    for insertion in INSERTIONS:
        assert result.count(insertion) == 1
        result = result.replace(insertion, '')
    assert result.count(SSID) == 1
    return result.replace(SSID, '${defaults?.ssid || "OpenWrt"}')

class ReviewedGenerators(unittest.TestCase):
    def test_allowlist_is_exactly_the_two_unmodified_fixtures(self):
        old = (kit/'tr3600/fixtures/mac80211-f0a60eee.uc').read_bytes()
        new = (kit/'tr3600/fixtures/mac80211-64900e75.uc').read_bytes()
        self.assertEqual(git_blob(old), 'd61786fa65023521d16fdf6bc499c2d26ee2d275')
        self.assertEqual(git_blob(new), 'c6c973040eb8c01f8fb8618337f9d1cf3cce4447')
        self.assertEqual(defaults.REVIEWED_BLOBS, {git_blob(old), git_blob(new)})
        self.assertEqual(old.count(b'const bands_order = [ "6G", "5G", "2G" ];'), 1)
        self.assertNotIn(b'60G', old)
        self.assertEqual(new, old.replace(
            b'const bands_order = [ "6G", "5G", "2G" ];',
            b'const bands_order = [ "60G", "6G", "5G", "2G" ];', 1))

class Generator(unittest.TestCase):
    fixture = 'tr3600/fixtures/mac80211-f0a60eee.uc'
    bands_order = 'const bands_order = [ "6G", "5G", "2G" ];'
    def setUp(self):
        (kit/'reports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='wifi-generator-', dir=kit/'reports')
        self.root = Path(self.temp.name)
        self.stock = (kit/self.fixture).read_bytes()
        self.target = self.root/path
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(self.stock)
    def tearDown(self): self.temp.cleanup()
    def assert_defaults(self, result):
        self.assertIn('channel = 36;', result)
        self.assertIn('htmode = "HE80";', result)
        self.assertIn('Cudy-TR3600-5G', result)
        self.assertIn('if (radio_exists(phy.path, macaddr, phy_name, radio.index))\n\t\t\tcontinue;', result)
        self.assertIn("set ${si}.disabled='${defaults ? 0 : 1}'", result)
        self.assertIn('cudy_tr3600 && band_name == "5G" && band.he', result)
        self.assertIn('== "cudy,tr3600-v1"', result)
        self.assertEqual(result.count(self.bands_order), 1)
        self.assertEqual(without_defaults(result).encode(), self.stock)
    def test_exact_pinned_layout_patches_defaults_and_keeps_existing_radio_skip(self):
        self.assertFalse((self.root/'package/kernel/mac80211/files/lib/wifi/mac80211.uc').exists())
        defaults.patch(self.root)
        self.assert_defaults(self.target.read_text(encoding='utf-8'))
    def test_wrong_old_layout_fails_without_modifying_it(self):
        self.target.unlink()
        old = self.root/'package/kernel/mac80211/files/lib/wifi/mac80211.uc'
        old.parent.mkdir(parents=True); old.write_bytes(self.stock)
        with self.assertRaises(FileNotFoundError): defaults.patch(self.root)
        self.assertEqual(old.read_bytes(), self.stock)
    def test_unexpected_generator_is_rejected_before_write(self):
        altered = self.stock + b'\n// unexpected source\n'
        self.target.write_bytes(altered)
        with self.assertRaises(AssertionError) as caught:
            defaults.patch(self.root)
        self.assertIn('Unexpected locked OpenWrt wireless generator', str(caught.exception))
        self.assertEqual(self.target.read_bytes(), altered)
    def test_second_patch_is_rejected_without_rewriting_result(self):
        defaults.patch(self.root)
        first = self.target.read_bytes()
        with self.assertRaises(AssertionError): defaults.patch(self.root)
        self.assertEqual(self.target.read_bytes(), first)

class CurrentGenerator(Generator):
    fixture = 'tr3600/fixtures/mac80211-64900e75.uc'
    bands_order = 'const bands_order = [ "60G", "6G", "5G", "2G" ];'

if __name__ == '__main__': unittest.main(verbosity=2)
