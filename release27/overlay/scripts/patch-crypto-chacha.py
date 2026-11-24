#!/usr/bin/env python3
"""Patch OpenWrt 6.12 crypto.mk so ChaCha-Poly1305 ESP has algorithm drivers.

The packaged kmod-crypto-chacha20poly1305 only installs the rfc7539esp
template. kernel 6.12 still spawns crypto API "chacha20" (skcipher) and
"poly1305" (shash) to create rfc7539esp(chacha20,poly1305). Those drivers
are chacha_generic.ko and poly1305_generic.ko; this tree has no
kmod-crypto-chacha20 / kmod-crypto-poly1305 packages for them.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

AEAD_OLD = """define KernelPackage/crypto-chacha20poly1305
  TITLE:=ChaCha20-Poly1305 AEAD support, RFC7539 (used by strongSwan IPsec VPN)
  DEPENDS:=+kmod-crypto-aead +kmod-crypto-manager
  KCONFIG:=CONFIG_CRYPTO_CHACHA20POLY1305
  FILES:=$(LINUX_DIR)/crypto/chacha20poly1305.ko
  AUTOLOAD:=$(call AutoLoad,09,chacha20poly1305)
  $(call AddDepends/crypto)
endef
"""

AEAD_NEW = """define KernelPackage/crypto-chacha20poly1305
  TITLE:=ChaCha20-Poly1305 AEAD support, RFC7539 (used by strongSwan IPsec VPN)
  DEPENDS:=+kmod-crypto-aead +kmod-crypto-manager \\
	+kmod-crypto-lib-chacha20 +kmod-crypto-lib-poly1305
  KCONFIG:=CONFIG_CRYPTO_CHACHA20POLY1305 \\
	CONFIG_CRYPTO_CHACHA20 \\
	CONFIG_CRYPTO_POLY1305
  FILES:=$(LINUX_DIR)/crypto/chacha20poly1305.ko \\
	$(LINUX_DIR)/crypto/chacha_generic.ko \\
	$(LINUX_DIR)/crypto/poly1305_generic.ko
  AUTOLOAD:=$(call AutoLoad,09,chacha_generic poly1305_generic chacha20poly1305)
  $(call AddDepends/crypto)
endef
"""

CHACHA_MIPS_OLD = """define KernelPackage/crypto-lib-chacha20/mips32r2
  KCONFIG+=CONFIG_CRYPTO_CHACHA_MIPS
  FILES:=$(LINUX_DIR)/arch/mips/crypto/chacha-mips.ko
endef
"""

CHACHA_MIPS_NEW = """define KernelPackage/crypto-lib-chacha20/mips32r2
  KCONFIG+=CONFIG_CRYPTO_CHACHA_MIPS
  FILES+=$(LINUX_DIR)/arch/mips/crypto/chacha-mips.ko
  AUTOLOAD:=$(call AutoLoad,09,chacha-mips)
endef
"""

# CONFIG_CPU_MIPS32_R2 lives in the kernel defconfig and may be unset
# when package makefiles are parsed. Also bind the MIPS32r2 variant to
# this device target so chacha-mips.ko is actually packaged.
CHACHA_IFEQ_OLD = """ifeq ($(CONFIG_CPU_MIPS32_R2),y)
  KernelPackage/crypto-lib-chacha20/$(ARCH)=\\
	  $(KernelPackage/crypto-lib-chacha20/mips32r2)
endif
"""

CHACHA_IFEQ_NEW = """ifeq ($(CONFIG_CPU_MIPS32_R2),y)
  KernelPackage/crypto-lib-chacha20/$(ARCH)=\\
	  $(KernelPackage/crypto-lib-chacha20/mips32r2)
endif

# MT7628 / mt76x8 is MIPS32r2; do not rely only on CONFIG_CPU_MIPS32_R2
# being visible in the OpenWrt .config at package parse time.
ifneq ($(CONFIG_TARGET_ramips_mt76x8),)
  KernelPackage/crypto-lib-chacha20/$(ARCH)=\\
	  $(KernelPackage/crypto-lib-chacha20/mips32r2)
endif
"""

POLY_MIPS_OLD = """define KernelPackage/crypto-lib-poly1305/mips
  KCONFIG+=CONFIG_CRYPTO_POLY1305_MIPS
  FILES:=$(LINUX_DIR)/arch/mips/crypto/poly1305-mips.ko
endef
"""

POLY_MIPS_NEW = """define KernelPackage/crypto-lib-poly1305/mips
  KCONFIG+=CONFIG_CRYPTO_POLY1305_MIPS
  FILES+=$(LINUX_DIR)/arch/mips/crypto/poly1305-mips.ko
  AUTOLOAD:=$(call AutoLoad,09,poly1305-mips)
endef
"""

REPLACEMENTS = (
    ('crypto-chacha20poly1305', AEAD_OLD, AEAD_NEW),
    ('crypto-lib-chacha20/mips32r2', CHACHA_MIPS_OLD, CHACHA_MIPS_NEW),
    ('CONFIG_CPU_MIPS32_R2 bind', CHACHA_IFEQ_OLD, CHACHA_IFEQ_NEW),
    ('crypto-lib-poly1305/mips', POLY_MIPS_OLD, POLY_MIPS_NEW),
)


def already_patched(text: str) -> bool:
    return (
        'chacha_generic.ko' in text
        and 'poly1305_generic.ko' in text
        and 'CONFIG_TARGET_ramips_mt76x8' in text
        and 'AUTOLOAD:=$(call AutoLoad,09,chacha-mips)' in text
        and 'AUTOLOAD:=$(call AutoLoad,09,poly1305-mips)' in text
        and 'FILES+=$(LINUX_DIR)/arch/mips/crypto/chacha-mips.ko' in text
        and 'FILES+=$(LINUX_DIR)/arch/mips/crypto/poly1305-mips.ko' in text
    )


def apply_patch(text: str) -> str:
    if already_patched(text):
        return text
    for name, old, new in REPLACEMENTS:
        if old not in text:
            raise SystemExit(f'crypto.mk does not match expected {name} block; refusing to patch')
        text = text.replace(old, new, 1)
    if not already_patched(text):
        raise SystemExit('crypto.mk patch did not produce the expected result')
    return text


def selftest() -> None:
    sample = AEAD_OLD + '\n' + CHACHA_MIPS_OLD + '\n' + CHACHA_IFEQ_OLD + '\n' + POLY_MIPS_OLD
    out = apply_patch(sample)
    assert 'chacha_generic.ko' in out
    assert 'poly1305_generic.ko' in out
    assert 'AutoLoad,09,chacha_generic poly1305_generic chacha20poly1305' in out
    assert 'FILES+=$(LINUX_DIR)/arch/mips/crypto/chacha-mips.ko' in out
    assert 'FILES+=$(LINUX_DIR)/arch/mips/crypto/poly1305-mips.ko' in out
    assert 'CONFIG_TARGET_ramips_mt76x8' in out
    assert apply_patch(out) == out
    print('patch-crypto-chacha selftest ok')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('crypto_mk', nargs='?', type=Path, help='Path to package/kernel/linux/modules/crypto.mk')
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.crypto_mk:
        raise SystemExit('crypto.mk path is required unless --selftest')
    path = args.crypto_mk
    text = path.read_text()
    patched = apply_patch(text)
    if patched == text:
        print(f'already patched: {path}')
        return
    shutil.copyfile(path, path.with_suffix(path.suffix + '.orig'))
    path.write_text(patched)
    print(f'patched {path}')


if __name__ == '__main__':
    main()
