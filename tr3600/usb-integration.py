#!/usr/bin/env python3
"""Add per-share disk guard and metadata settings to the exact locked Samba init."""
import hashlib
from pathlib import Path
import sys

SOURCE_BLOB = '468ba553a2b87ba3cb8d1ca2b9f638f820764a3d'
RELATIVE = Path('feeds/packages/net/samba4/files/samba.init')

def patch_text(source):
    raw=source.encode()
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==SOURCE_BLOB, 'Unexpected pinned Samba init'
    old='\tconfig_get_sane vfs_objects "$1" vfs_objects\n'
    assert source.count(old)==1
    source=source.replace(old,old+'\tconfig_get_sane cudy_usb "$1" cudy_usb\n')
    old='\t\t# always enable io_uring if we can'
    assert source.count(old)==1
    new='''		# Only project-managed USB shares get the disk guard and per-volume TDB.
		# Paths/ids are validated before interpolation into root preexec.
		if [ -n "$cudy_usb" ]; then
			if [ "$cudy_usb" != "$1" ] || ! printf '%s\\n' "$cudy_usb" | grep -Eq '^usb_[A-Za-z0-9_]+$'; then
				printf '\\troot preexec = /bin/false\\n\\troot preexec close = yes\\n'
			elif [ "$path" != "/mnt/cudy-usb/$cudy_usb" ] && [ "$path" != '/mnt/usb' ]; then
				printf '\\troot preexec = /bin/false\\n\\troot preexec close = yes\\n'
			else
				printf '\\troot preexec = /usr/libexec/cudy-usb guard %s %s\\n' "$cudy_usb" "$path"
				printf '\\troot preexec close = yes\\n\\tveto files = /.samba-metadata/\\n'
				printf '\\tfruit:encoding = native\\n\\tfruit:metadata = stream\\n\\tfruit:veto_appledouble = no\\n'
				vfs_objects='catia fruit streams_xattr'
				if [ "$read_only" != 'yes' ]; then
					vfs_objects="$vfs_objects xattr_tdb"
					printf '\\txattr_tdb:file = %s/.samba-metadata/xattr.tdb\\n' "$path"
				fi
			fi
		fi

'''
    return source.replace(old,new+old)

def patch(root):
    path=Path(root)/RELATIVE
    path.write_text(patch_text(path.read_text(encoding='utf-8')),encoding='utf-8',newline='\n')

if __name__=='__main__': patch(sys.argv[1])
