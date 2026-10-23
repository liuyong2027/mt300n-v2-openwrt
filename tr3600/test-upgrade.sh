#!/usr/bin/env bash
set -euo pipefail
. tr3600/cudy-upgrade.sh
fixture="$(mktemp -d)"
trap 'rm -rf "$fixture"' EXIT
export CUDY_UPGRADE_TMP="$fixture"
log="$fixture/events"
cudy_tr3600_param() {
    case "$1" in
        dual_boot) echo "${DUAL:-Y}";;
        boot_image_slot) echo "$ACTIVE";;
        upgrade_image_slot) echo "$NEXT";;
        upgrade_kernel_part) echo "$KERNEL";;
        upgrade_rootfs_part) echo "$ROOTFS";;
    esac
}
fw_printenv() { echo "${ENV_ACTIVE:-$ACTIVE}"; }
nand_find_ubi() { echo ubi0; }
nand_find_volume() {
    case "$2" in
        u-boot-env) echo ubi0_0;;
        kernel|kernel2) echo ubi0_1;;
        rootfs|rootfs2) echo ubi0_2;;
    esac
}
nand_verify_tar_file() { return 0; }
tar() {
    if [ "$1" = tf ]; then echo sysupgrade-cudy_tr3600-v1/; else printf image; fi
}
identify() { echo squashfs; }
nand_upgrade_prepare_ubi() {
    printf 'prepare:%s:%s\n' "$CI_KERNPART" "$CI_ROOTPART" >> "$log"
    [ "${FAIL:-}" != prepare ]
}
ubiupdatevol() {
    printf 'write:%s\n' "$1" >> "$log"
    [ "${FAIL:-}" != "$1" ]
}
fw_setenv() {
    echo commit >> "$log"
    cp "$2" "$fixture/env-result"
    [ "${FAIL:-}" != env ]
}
sync() { :; }
nand_do_upgrade_success() { echo success >> "$log"; }
mkdir() { :; }
for ACTIVE in 0 1; do
    NEXT=$((1-ACTIVE))
    if [ "$ACTIVE" = 0 ]; then KERNEL=kernel2; ROOTFS=rootfs2; else KERNEL=kernel; ROOTFS=rootfs; fi
    : > "$log"
    cudy_tr3600_do_upgrade fixture.bin
    grep -qx "prepare:$KERNEL:$ROOTFS" "$log"
    grep -qx "dual_boot.current_slot $NEXT" "$fixture/env-result"
    [ "$(tail -n 2 "$log" | head -n 1)" = commit ]
    [ "$(tail -n 1 "$log")" = success ]
    for FAIL in prepare /dev/ubi0_1 /dev/ubi0_2; do
        : > "$log"
        if cudy_tr3600_do_upgrade fixture.bin; then echo 'Failure accepted'; exit 1; fi
        ! grep -q commit "$log"
        ! grep -q success "$log"
    done
    FAIL=env
    : > "$log"
    if cudy_tr3600_do_upgrade fixture.bin; then exit 1; fi
    ! grep -q success "$log"
    unset FAIL
    ENV_ACTIVE="$NEXT"
    : > "$log"
    if cudy_tr3600_do_upgrade fixture.bin; then exit 1; fi
    [ ! -s "$log" ]
    unset ENV_ACTIVE
done
if cudy_tr3600_slot_pair 0 kernel rootfs; then exit 1; fi
echo 'Dual-slot upgrade success/failure ordering fixtures passed'
