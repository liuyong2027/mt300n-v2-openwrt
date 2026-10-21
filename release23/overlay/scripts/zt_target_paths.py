"""Resolve firmware symlinks inside the firmware root, never the CI host root."""
import os
from pathlib import Path, PurePosixPath


def resolve_in_root(root, path):
    root=Path(root).absolute()
    path=Path(path)
    relative=path.relative_to(root) if path.is_absolute() else path
    pending=list(relative.parts)
    current=root
    links=0
    while pending:
        part=pending.pop(0)
        if part in ('', '.'):
            continue
        if part=='..':
            if current==root:
                raise ValueError('Target path escapes rootfs')
            current=current.parent
            continue
        candidate=current/part
        if candidate.is_symlink():
            links+=1
            if links>40:
                raise ValueError('Target symlink loop')
            target=PurePosixPath(os.readlink(candidate))
            if target.is_absolute():
                current=root
                pending=list(target.parts[1:])+pending
            else:
                pending=list(target.parts)+pending
        else:
            current=candidate
    current.relative_to(root)
    return current
