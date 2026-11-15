#!/usr/bin/env bash
# Host reproduction of issue #18 against fstools 16718b6e (OpenWrt 25.12.6).
# Unpatched libblkid-tiny treats a missing exFAT label as an I/O error when
# errno is stale. The package patch must make that volume succeed and must
# leave a labelled exFAT volume and a labelled FAT volume unchanged.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../.." && pwd)
patch_file=$repo/tr3600/fstools/patches/0001-libblkid-tiny-reset-errno-before-probe.patch
commit=16718b6e3c0fc7db7be6ae5848db0eae88ac8a8b
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

git init -q "$work/fstools"
git -C "$work/fstools" remote add origin https://github.com/openwrt/fstools.git
git -C "$work/fstools" fetch --depth 1 origin "$commit"
git -C "$work/fstools" checkout --detach FETCH_HEAD
test "$(git -C "$work/fstools" rev-parse HEAD)" = "$commit"

python3 "$here/make-images.py" "$work/images"

compile_probe() {
	local src=$1 dest=$2
	local sources=(
		encode.c libblkid-tiny.c probe.c exfat.c ext.c jffs2.c vfat.c
		ntfs.c hfs.c swap.c ubi.c ubifs.c squashfs.c btrfs.c f2fs.c
	)
	local args=()
	local name
	for name in "${sources[@]}"; do
		args+=("$src/libblkid-tiny/$name")
	done
	gcc -std=gnu99 -Wall -Werror -O2 \
		-I"$src/libblkid-tiny" -I"$here" \
		"${args[@]}" "$here/probe-harness.c" -o "$dest"
}

cp -a "$work/fstools" "$work/unpatched"
compile_probe "$work/unpatched" "$work/probe-before"

cp -a "$work/fstools" "$work/patched"
patch -p1 -d "$work/patched" < "$patch_file"
compile_probe "$work/patched" "$work/probe-after"

python3 - "$work" <<'PY'
import subprocess
import sys
from pathlib import Path

work = Path(sys.argv[1])

def probe(binary, image, errno):
    line = subprocess.check_output(
        [str(work / binary), str(work / 'images' / image), str(errno)],
        text=True).strip()
    fields = {}
    for part in line.split():
        key, value = part.split('=', 1)
        fields[key] = value
    print(f'{binary} {image} errno={errno}: {line}')
    return fields

def expect(got, **want):
    for key, value in want.items():
        if got.get(key) != value:
            raise SystemExit(f'expected {key}={value!r}, got {got}')

unlabeled = dict(rc='0', err='0', id='exfat', uuid='A1B2-C3D4', label='', ver='1.0')
hidden = dict(rc='0', err='-2', id='exfat', uuid='', label='', ver='')
labeled = dict(rc='0', err='0', id='exfat', uuid='A1B2-C3D4', label='KING', ver='1.0')
vfat = dict(rc='0', err='0', id='vfat', label='KING')

expect(probe('probe-before', 'exfat-unlabeled.img', 0), **unlabeled)
expect(probe('probe-before', 'exfat-unlabeled.img', 2), **hidden)
expect(probe('probe-before', 'exfat-labeled.img', 2), **labeled)
expect(probe('probe-before', 'vfat-labeled.img', 2), **vfat)
expect(probe('probe-after', 'exfat-unlabeled.img', 0), **unlabeled)
expect(probe('probe-after', 'exfat-unlabeled.img', 2), **unlabeled)
expect(probe('probe-after', 'exfat-labeled.img', 2), **labeled)
expect(probe('probe-after', 'vfat-labeled.img', 2), **vfat)
print('unlabeled exFAT is detected with a stale errno, and labelled exFAT/FAT are unchanged')
PY
