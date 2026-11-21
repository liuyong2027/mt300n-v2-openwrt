"""Apply the directory-type correction to the pinned Samba 4.22.7 package."""
import hashlib
from pathlib import Path
import shutil
import sys


MAKEFILE_SHA256 = '6963698bd8a32a15dfc7e00136c741e944490d82c1ade6867a89e9fcec97652b'
PATCH_NAME = '200-dos-mode-use-actual-file-type.patch'


def prepare(root):
    package = root / 'feeds/packages/net/samba4'
    makefile = package / 'Makefile'
    data = makefile.read_bytes()
    if hashlib.sha256(data).hexdigest() != MAKEFILE_SHA256:
        raise ValueError('Pinned Samba 4.22.7-r3 package changed')
    text = data.decode('utf-8')
    if text.count('PKG_RELEASE:=3\n') != 1:
        raise ValueError('Pinned Samba package release changed')
    patch = package / 'patches' / PATCH_NAME
    if patch.exists():
        raise ValueError('Samba directory-type patch already exists')
    patch.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).parent / 'patches' / PATCH_NAME, patch)
    makefile.write_text(text.replace('PKG_RELEASE:=3\n', 'PKG_RELEASE:=4\n', 1),
                        encoding='utf-8', newline='\n')


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
