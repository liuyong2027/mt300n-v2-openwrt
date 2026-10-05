Cudy TR3600 v1 / Mango 20-test-failover1 port, test2 (pre-release)

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
L2TP/IPsec server and Dynamic DNS are excluded at the owner request.
PPP/PPPoE WAN support and ZeroTier remain. This is a test build, not a
production release. On keep-settings upgrades, retired configurations
are moved to a root-private backup and only owned VPN firewall sections
are removed; LAN/WAN, proxy, USB shares and unrelated firewall rules remain.

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

Next firmware network defaults (2026-10-05):
The WAN eth0 EEE / Tx LPI workaround is included with ethtool and runs
on WAN/LAN ifup for cudy,tr3600-v1. Existing Wi-Fi configuration is kept.
When generating a new 5 GHz radio, use channel 36, HE80 / 80 MHz and a
separate default SSID Cudy-TR3600-5G. Set country and a secure password
before enabling a fresh AP; no owner's wireless password is embedded.
The running user's router was repaired in place: gateway packet loss
fell from 40% to 0%; reported 5 GHz direct throughput was 284/50.7 Mbps,
and after returning to proxy mode 359/55 Mbps, with normal page opening.
These are user-reported measurements. A new image still requires the
complete build and packed-image verification before delivery.
Optional unified Wi-Fi: Network / 双频合一. Disabled by default. Select
two enabled LAN APs, a shared SSID/security/password, and optionally enable
local usteer band steering with full wpad and 802.11k/v. Leaving the shared
password blank reuses the selected 5 GHz password. Disabling unification
restores the original AP options and steering configuration from a private
backup retained on keep-settings upgrades. Guest/repeater interfaces are
excluded. Steering requests supported clients to use 5 GHz with adequate
signal; it does not guarantee that every client chooses the best band.
See tr3600/WIFI-UNIFICATION.md for behavior and validation limits.

Status LEDs: System / 指示灯. Recommended status mode is the new-image default;
optional 23:00-07:00 night mode is disabled by default. White solid = recent
connectivity confirmed; white slow = waiting; red solid = local exit offline;
red slow = repeated upstream/proxy failure. Preserve system boot/upgrade/rescue.
Only observe proxy probes; LED code never changes nodes, routes or services.
See tr3600/LED-STATUS.txt. This source addition has not been rebuilt or flashed.

Test2 upgrade: back up your configuration first. From an existing matching
TR3600 OpenWrt image, keep settings can retain configured USB mounts/shares
and owner Wi-Fi/proxy settings. USB/iPhone permissions fixed on the current
router are owner configuration, not prefilled per-device defaults. No disk
UUID, node credentials, Dynu credentials or wireless password is embedded.
Physical LED, band steering and full new-image upgrade/reboot acceptance
remain required. Current router WAN was observed at 100Mb/s; firmware
cannot guarantee a cable/port negotiates gigabit. Test2 is not yet built.
