#!/usr/bin/env python3
"""Restore only the pinned diagnostic target for preflight; never publishes it."""
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile

archive=Path(sys.argv[1]).read_bytes()
assert hashlib.sha256(archive).hexdigest()=='c28d567618837a7d5eaac77092595898222b970a88f702d07c4dc788fc53fd21'
root=Path(sys.argv[2]).resolve()
assert not (root/'openwrt').exists()
with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as source:
    members=source.getmembers()
    seen=set()
    for member in members:
        name=PurePosixPath(member.name)
        assert not name.is_absolute() and '..' not in name.parts and name.parts[0]=='openwrt'
        assert member.name not in seen; seen.add(member.name)
        assert member.isdir() or member.isfile() or member.issym()
    # Write all regular files before creating any links, preventing extraction through a link.
    for member in members:
        path=root/member.name
        if member.isdir(): path.mkdir(parents=True,exist_ok=True)
        elif member.isfile():
            path.parent.mkdir(parents=True,exist_ok=True)
            with source.extractfile(member) as stream: path.write_bytes(stream.read())
            path.chmod(member.mode)
    for member in members:
        if member.issym():
            path=root/member.name; path.parent.mkdir(parents=True,exist_ok=True)
            os.symlink(member.linkname,path)
print('Restored pinned prior target for verification preflight only')
