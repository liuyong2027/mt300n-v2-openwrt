Cudy TR3600 v1 / Mango 20-test-failover1 port, test1

This is a test firmware, based on application commit
1f6169759396a31d2e3beec35d300c1fe4f2eaec, OpenWrt 25.12.5
f0a60eee2fe051741c643ea6118718aae1ef17fb and the original locked feeds.
The Mango proxy UI, R3 Xray patch, subscription, failover and ZeroTier
packages are retained. The kernel uses OpenWrt Filogic defaults rather
than the Mango MT76x8 production kernel flag set.
User-requested USB file sharing and Wi-Fi repeater support are included:
Samba4 + LuCI Network Shares, block-mount, USB mass storage/UAS, ext4,
exFAT, FAT and NTFS3; relayd + LuCI relay protocol for IPv4 pseudo bridging.
Wireless client/routed repeater configuration uses the normal LuCI UI.

Only TR3600 hardware v1 (MT7987B / 512 MiB RAM / 256 MiB NAND).
Build and emulation checks do not prove actual router acceptance.

From stock Cudy firmware:
1. Confirm TR3600 v1 on the label and save the stock configuration.
2. Obtain official Develop_files_for_TR3600.zip from:
   https://www.cudy.com/zh-cn/pages/download-center/tr3600-1-0
3. Read the official README. Flash its Intermediate firmware/
   cudy_tr3600-v1-sysupgrade_260715.bin through the Cudy web interface.
4. After it boots, install this TR3600 squashfs-sysupgrade.bin through
   OpenWrt LuCI, with Keep settings disabled (-n). Do not use forced upgrade.
5. Connect by Ethernet. Fresh LAN is http://192.168.8.1 . Set the root
   password and configure Wi-Fi country/security/enable in LuCI.

The build includes the official configurable UBI rootfs/boot parameter
kernel patch and a TR3600-only dual-slot upgrade dispatcher. The helper
checks active/inactive slot names and writes both inactive volumes before
changing boot environment. Shared rootfs_data is recreated; this is not a
guarantee of automatic rollback or retention of vendor configuration.
Bootloader, Factory and bdinfo partitions are not written by this helper.

Hardware DTS corrections: PWM0@GPIO13 for fan, GPIO6 supply, red GPIO46,
white GPIO48, radio MAC offsets base+0/base+16 and active thermal maps.
Device support PR: https://github.com/openwrt/openwrt/pull/24596
Hardware review: https://github.com/openwrt/openwrt/pull/24596#issuecomment-5226298465
DTS fixes source: https://github.com/hyqhyq3/openwrt-cudy-tr3600/blob/main/cudy-tr3600-v1-fixes.patch
Vendor dual-image patch and notes originate from the official development
ZIP above. Matching upstream sources keep their original licenses.

After flashing, verify fan operation, LAN/WAN, 2.4/5 GHz, USB3, proxy
connectivity and failover on the actual router before relying on this build.
USB sharing: configure the disk under System / Mount Points, then set the
directory and access permissions under Services / Network Shares. No disk
is reformatted and no unauthenticated share is created by this build.
Repeater: use Network / Wireless to scan and join the upstream Wi-Fi,
create a DHCP client interface (e.g. wwan) in the WAN firewall zone, and
configure a local AP. Keep the local LAN on a different subnet. For IPv4
pseudo bridging, configure relayd through Network / Interfaces instead.
These are OpenWrt equivalents; the Cudy App, cloud management, Cudy Mesh
and vendor UI are not included.
