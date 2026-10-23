#!/usr/bin/env python3
"""Retain the actual image and tools so failed checks can be rerun directly."""
from pathlib import Path
import tarfile
kit = Path(__file__).resolve().parents[1]
tree = kit / 'openwrt'
reports = kit / 'reports'
images = list((tree/'bin/targets/mediatek/filogic').glob('*cudy_tr3600-v1-squashfs-sysupgrade.bin'))
linux = list((tree/'build_dir').glob('target-*/linux-mediatek_filogic/linux-6.12.*'))
assert len(images) == 1, images
assert len(linux) == 1, linux
files = [images[0], tree/'.config', linux[0]/'System.map', linux[0]/'.config']
files += [tree / p for p in ('staging_dir/host/bin/unsquashfs4', 'staging_dir/host/bin/fwtool', 'staging_dir/hostpkg/bin/jsmin')]
files += [reports / p for p in ('runtime-validation.json','resolved.config','feed-commits.txt','tr3600-source.json')]
for p in files:
    assert p.is_file(), p
with tarfile.open(reports/'packed-verification-inputs.tar.xz', 'w:xz') as archive:
    for p in files:
        archive.add(p, arcname=str(p.relative_to(kit)), recursive=False)
print('Preserved the compiled image, host verification tools, kernel symbols and reports')
