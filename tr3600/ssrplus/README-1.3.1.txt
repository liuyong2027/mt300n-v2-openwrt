TR3600 1.3.1 — unlabeled exFAT detection on the 1.3.0 image

Base: release tag tr3600-v1.3.0 (9d37e9374652b9f81a7a2fcb2074eb61ef23c052).
OpenWrt 25.12.6. cudy-release = tr3600-ssrplus-ikev2-1.3.1.

The device image only builds sysupgrade.bin. There is no factory image
in the TR3600 device profile.

fstools stays at 2026.05.23~16718b6e. PKG_RELEASE becomes 2 because
package/system/fstools/patches/0001-libblkid-tiny-reset-errno-before-probe.patch
clears errno before each libblkid-tiny probe. An exFAT volume with no
0x83 label is then reported by block info. Labelled exFAT and FAT are unchanged.

Host check, before a firmware build:

    bash tr3600/fstools/host-test/test-unlabeled-exfat.sh
