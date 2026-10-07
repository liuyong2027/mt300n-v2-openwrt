#!/bin/sh
# Cudy R126 dual-slot upgrade. Never write bootloader/calibration partitions.
cudy_tr3600_param() {
    cat "/sys/module/boot_param/parameters/$1"
}

cudy_tr3600_slot_pair() {
    case "$1:$2:$3" in
        0:kernel2:rootfs2) CUDY_SLOT=1;;
        1:kernel:rootfs) CUDY_SLOT=0;;
        *) echo 'Invalid Cudy boot slot/volume parameters' >&2; return 1;;
    esac
}

cudy_tr3600_do_upgrade() {
    local image="$1" active kernel rootfs current ubidev envvol work="${CUDY_UPGRADE_TMP:-/tmp}"
    [ "$(cudy_tr3600_param dual_boot)" = Y ] || return 1
    active="$(cudy_tr3600_param boot_image_slot)" || return 1
    kernel="$(cudy_tr3600_param upgrade_kernel_part)" || return 1
    rootfs="$(cudy_tr3600_param upgrade_rootfs_part)" || return 1
    cudy_tr3600_slot_pair "$active" "$kernel" "$rootfs" || return 1
    [ "$(cudy_tr3600_param upgrade_image_slot)" = "$CUDY_SLOT" ] || return 1
    current="$(fw_printenv -n dual_boot.current_slot)" || return 1
    [ "$current" = "$active" ] || return 1
    ubidev="$(nand_find_ubi ubi)"
    [ "$ubidev" = ubi0 ] || return 1
    envvol="$(nand_find_volume "$ubidev" u-boot-env)"
    [ "$envvol" = ubi0_0 ] || return 1
    local board_dir kernel_length rootfs_length rootfs_type
    nand_verify_tar_file "$image" cat || return 1
    board_dir="$(tar tf "$image" | grep -m 1 '^sysupgrade-.*/$')"
    board_dir="${board_dir%/}"
    [ "$board_dir" = sysupgrade-cudy_tr3600-v1 ] || return 1
    tar xOf "$image" "$board_dir/kernel" > "$work/cudy-kernel.bin" || return 1
    tar xOf "$image" "$board_dir/root" > "$work/cudy-root.bin" || return 1
    kernel_length="$(wc -c < "$work/cudy-kernel.bin")"
    rootfs_length="$(wc -c < "$work/cudy-root.bin")"
    [ "$kernel_length" -gt 0 ] && [ "$rootfs_length" -gt 0 ] || return 1
    rootfs_type="$(identify "$work/cudy-root.bin" cat '')"
    [ "$rootfs_type" = squashfs ] || return 1
    CI_UBIPART=ubi
    CI_KERNPART="$kernel"
    CI_ROOTPART="$rootfs"
    # The normal NAND helper recreates shared rootfs_data; sysupgrade restores
    # the requested configuration backup. Initial vendor migration must use -n.
    nand_upgrade_prepare_ubi "$rootfs_length" "$rootfs_type" "$kernel_length" 0 || return 1
    local kernvol rootvol
    kernvol="$(nand_find_volume "$ubidev" "$kernel")"
    rootvol="$(nand_find_volume "$ubidev" "$rootfs")"
    [ -n "$kernvol" ] && [ -n "$rootvol" ] || return 1
    ubiupdatevol "/dev/$kernvol" "$work/cudy-kernel.bin" || return 1
    ubiupdatevol "/dev/$rootvol" "$work/cudy-root.bin" || return 1
    # Commit both environment keys in one transaction after both writes pass.
    mkdir -p /var/lock
    printf 'dual_boot.current_slot %s\ndual_boot.slot_%s_invalid 0\n' "$CUDY_SLOT" "$CUDY_SLOT" > "$work/cudy-env.txt"
    fw_setenv -s "$work/cudy-env.txt" || return 1
    sync
    nand_do_upgrade_success
}
