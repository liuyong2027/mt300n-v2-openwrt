#!/usr/bin/env python3
"""Cover the locked v25.12.5 LuCI feed and the byte-identical v25.12.6 feed."""
import base64
import hashlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FEED_25_12_5 = '128a7812f4be233c5dd7f7466f534fd888785caf'
FEED_25_12_6 = '75a306df84a020c57a631ef5b4c02ace56d93387'
ORIGINAL_SHA256 = '3f655d29cfc14f3d2db03c3e97f3a61f8825e49541405d0ea05387d980272a27'
PATCHED_SHA256 = 'd4d4a8d7b7660fdf787f459e6ff7f82894cad68811094dee48834dcff918936f'

spec = importlib.util.spec_from_file_location(
    'patch_ucitrack_feed', ROOT / 'tr3600/ssrplus/patch-ucitrack-feed.py')
feed_patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed_patch)

def load_optimizer(tree):
    path = tree / 'scripts/optimize-ucitrack.py'
    module_spec = importlib.util.spec_from_file_location('optimize_ucitrack_reviewed', path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module

class UcitrackFeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = base64.b64decode((ROOT / 'release20-test-failover1-source.zip.b64').read_text().strip(), validate=True)
        cls.bundle = zipfile.ZipFile(io.BytesIO(data))
        cls.original_optimizer = cls.bundle.read('scripts/optimize-ucitrack.py').decode()
        cls.fixture = cls.bundle.read('tests/fixtures/ucitrack-reviewed.sh')
        cls.bundled_test = cls.bundle.read('tests/test_ucitrack_build.py')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self.tmp.name)
        (self.tree / 'scripts').mkdir()
        (self.tree / 'tests/fixtures').mkdir(parents=True)
        (self.tree / 'scripts/optimize-ucitrack.py').write_text(
            feed_patch.patch_text(self.original_optimizer), encoding='utf-8', newline='\n')
        (self.tree / 'tests/fixtures/ucitrack-reviewed.sh').write_bytes(self.fixture)
        (self.tree / 'tests/test_ucitrack_build.py').write_bytes(self.bundled_test)
        self.optimizer = load_optimizer(self.tree)
        self.openwrt = self.tree / 'openwrt'
        self.source = self.openwrt / self.optimizer.SOURCE_PATH
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(self.fixture)

    def tearDown(self):
        self.tmp.cleanup()

    def apply(self, commit, *, verify=False):
        with patch.object(self.optimizer.subprocess, 'check_output', return_value=commit + '\n'):
            return self.optimizer.optimize(self.openwrt, verify=verify)

    def test_checksums_and_allowlist_stay_exact(self):
        self.assertEqual(self.optimizer.ORIGINAL_SHA256, ORIGINAL_SHA256)
        self.assertEqual(self.optimizer.PATCHED_SHA256, PATCHED_SHA256)
        self.assertEqual(hashlib.sha256(self.fixture).hexdigest(), ORIGINAL_SHA256)
        self.assertEqual(self.optimizer.REVIEWED_FEED_COMMITS, {FEED_25_12_5, FEED_25_12_6})
        self.assertEqual(self.optimizer.FEED_COMMIT, FEED_25_12_5)
        self.assertNotIn("if commit != FEED_COMMIT:", (self.tree / 'scripts/optimize-ucitrack.py').read_text())

    def test_both_reviewed_feeds_patch_the_same_bytes(self):
        for commit in (FEED_25_12_5, FEED_25_12_6):
            with self.subTest(commit=commit):
                self.source.write_bytes(self.fixture)
                report = self.apply(commit)
                after = self.source.read_bytes()
                self.assertEqual(hashlib.sha256(after).hexdigest(), PATCHED_SHA256)
                self.assertEqual(after.replace(self.optimizer.PATCHED_CONDITION, self.optimizer.ORIGINAL_CONDITION, 1), self.fixture)
                self.assertEqual(report['feed_commit'], commit)
                self.assertEqual(report['status'], 'applied')
                self.assertTrue(report['changed'])
                before = self.source.read_bytes()
                with patch.object(Path, 'write_bytes', side_effect=AssertionError('reapply wrote')):
                    again = self.apply(commit)
                self.assertEqual(self.source.read_bytes(), before)
                self.assertEqual(again['status'], 'already-applied')

    def test_unknown_commit_and_changed_bytes_do_not_write(self):
        before = self.source.read_bytes()
        for verify in (False, True):
            with self.subTest(commit='unknown', verify=verify):
                with self.assertRaisesRegex(ValueError, 'feed commit differs'):
                    self.apply('unknown', verify=verify)
                self.assertEqual(self.source.read_bytes(), before)
        changed = before + b'# unreviewed\n'
        self.source.write_bytes(changed)
        for commit in (FEED_25_12_5, FEED_25_12_6):
            with self.subTest(commit=commit):
                with self.assertRaisesRegex(ValueError, 'source hash differs'):
                    self.apply(commit)
                self.assertEqual(self.source.read_bytes(), changed)

    def test_bundled_regressions_still_pass_on_the_patched_optimizer(self):
        completed = subprocess.run(
            [sys.executable, str(self.tree / 'tests/test_ucitrack_build.py')],
            cwd=self.tree, text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_second_feed_patch_is_rejected(self):
        patched = feed_patch.patch_text(self.original_optimizer)
        with self.assertRaisesRegex(ValueError, 'already present'):
            feed_patch.patch_text(patched)

if __name__ == '__main__':
    unittest.main(verbosity=2)
