#!/usr/bin/env python3
"""Regress actual pinned generator layout, defaults and fail-closed adaptation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

kit = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_defaults', kit/'tr3600/network-defaults.py')
defaults = importlib.util.module_from_spec(spec)
spec.loader.exec_module(defaults)
stock = (kit/'tr3600/fixtures/mac80211-f0a60eee.uc').read_bytes()
path = Path('package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc')

class Generator(unittest.TestCase):
    def setUp(self):
        (kit/'reports').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='wifi-generator-',dir=kit/'reports')
        self.root = Path(self.temp.name)
        self.target = self.root/path
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(stock)
    def tearDown(self): self.temp.cleanup()
    def test_exact_pinned_layout_patches_defaults_and_keeps_existing_radio_skip(self):
        self.assertFalse((self.root/'package/kernel/mac80211/files/lib/wifi/mac80211.uc').exists())
        defaults.patch(self.root)
        result=self.target.read_text(encoding='utf-8')
        self.assertIn('channel = 36;',result)
        self.assertIn('htmode = "HE80";',result)
        self.assertIn('Cudy-TR3600-5G',result)
        self.assertIn('if (radio_exists(phy.path, macaddr, phy_name, radio.index))\n\t\t\tcontinue;',result)
        self.assertIn("set ${si}.disabled='${defaults ? 0 : 1}'",result)
        self.assertIn('cudy_tr3600 && band_name == "5G" && band.he',result)
        self.assertIn('== "cudy,tr3600-v1"',result)
    def test_wrong_old_layout_fails_without_modifying_it(self):
        self.target.unlink()
        old=self.root/'package/kernel/mac80211/files/lib/wifi/mac80211.uc'
        old.parent.mkdir(parents=True); old.write_bytes(stock)
        with self.assertRaises(FileNotFoundError): defaults.patch(self.root)
        self.assertEqual(old.read_bytes(),stock)
    def test_unexpected_generator_is_rejected_before_write(self):
        altered=stock+b'\n// unexpected source\n'
        self.target.write_bytes(altered)
        with self.assertRaises(AssertionError): defaults.patch(self.root)
        self.assertEqual(self.target.read_bytes(),altered)
    def test_second_patch_is_rejected_without_rewriting_result(self):
        defaults.patch(self.root)
        first=self.target.read_bytes()
        with self.assertRaises(AssertionError): defaults.patch(self.root)
        self.assertEqual(self.target.read_bytes(),first)

if __name__=='__main__': unittest.main(verbosity=2)
