import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('target_paths',ROOT/'scripts/zt_target_paths.py')
paths=importlib.util.module_from_spec(spec); spec.loader.exec_module(paths)


@unittest.skipIf(os.name=='nt','Firmware uses POSIX symlinks; tested on Linux CI')
class TargetPaths(unittest.TestCase):
    def test_absolute_and_relative_links_stay_in_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'usr/bin').mkdir(parents=True)
            (root/'usr/bin/util-linux-flock').write_text('target ELF fixture')
            (root/'usr/bin/flock').symlink_to('/usr/bin/util-linux-flock')
            (root/'usr/bin/relative').symlink_to('flock')
            self.assertEqual(paths.resolve_in_root(root,root/'usr/bin/flock'),root/'usr/bin/util-linux-flock')
            self.assertEqual(paths.resolve_in_root(root,'usr/bin/relative'),root/'usr/bin/util-linux-flock')
    def test_escape_and_loop_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'escape').symlink_to('../outside')
            (root/'loop').symlink_to('loop')
            for name in ('escape','loop'):
                with self.assertRaises(ValueError): paths.resolve_in_root(root,name)
