#!/usr/bin/env python3
"""Synthetic volumes for the unlabeled-exFAT libblkid-tiny regression."""
import struct
import sys
from pathlib import Path


def write_exfat(path, label):
    sb = bytearray(512)
    sb[0:3] = b'\xeb\x76\x90'
    sb[3:11] = b'EXFAT   '
    struct.pack_into('<Q', sb, 64, 0)          # partition offset
    struct.pack_into('<Q', sb, 72, 64)         # volume length, sectors
    struct.pack_into('<I', sb, 80, 1)          # FAT offset
    struct.pack_into('<I', sb, 84, 1)          # FAT length
    struct.pack_into('<I', sb, 88, 2)          # cluster heap offset
    struct.pack_into('<I', sb, 92, 1)          # cluster count
    struct.pack_into('<I', sb, 96, 2)          # root directory cluster
    sb[100:104] = bytes((0xD4, 0xC3, 0xB2, 0xA1))  # prints as A1B2-C3D4
    sb[104] = 0                                # minor
    sb[105] = 1                                # major
    sb[108] = 9                                # 512-byte sectors
    sb[109] = 0                                # one sector per cluster
    sb[110] = 1                                # one FAT
    sb[510:512] = b'\x55\xaa'
    image = bytearray(8192)
    image[0:512] = sb
    struct.pack_into('<I', image, 512 + 8, 0xFFFFFFFF)  # cluster 2 end of chain
    root = 1024
    if label:
        encoded = label.encode('utf-16le')
        if 2 + len(encoded) > 32:
            raise SystemExit('label does not fit in one exFAT directory entry')
        entry = bytearray(32)
        entry[0] = 0x83
        entry[1] = len(label)
        entry[2:2 + len(encoded)] = encoded
        image[root:root + 32] = entry
    Path(path).write_bytes(image)


def write_vfat(path):
    sb = bytearray(512)
    sb[0:3] = b'\xeb\x3c\x90'
    sb[3:11] = b'MSDOS5.0'
    struct.pack_into('<H', sb, 11, 512)  # sector size
    sb[13] = 1                           # sectors per cluster
    struct.pack_into('<H', sb, 14, 1)    # reserved sectors
    sb[16] = 1                           # FAT count
    struct.pack_into('<H', sb, 17, 16)   # root directory entries
    struct.pack_into('<H', sb, 19, 32)   # total sectors
    sb[21] = 0xF8                        # media
    struct.pack_into('<H', sb, 22, 1)    # sectors per FAT
    sb[54:62] = b'FAT12   '
    sb[510:512] = b'\x55\xaa'
    image = bytearray(32 * 512)
    image[0:512] = sb
    entry = bytearray(32)
    entry[0:11] = b'KING       '
    entry[11] = 0x08                     # volume label
    image[1024:1056] = entry
    Path(path).write_bytes(image)


if __name__ == '__main__':
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    write_exfat(out / 'exfat-unlabeled.img', None)
    write_exfat(out / 'exfat-labeled.img', 'KING')
    write_vfat(out / 'vfat-labeled.img')
