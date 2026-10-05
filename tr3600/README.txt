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
L2TP/IPsec VPN server: Services / L2TP/IPsec VPN. Disabled by default.
Set your own username, password and IPsec PSK (12-128 supported characters),
choose a VPN /24 subnet different from LAN/upstream networks, then enable.
Multiple accounts and concurrent clients, with a separate PPP interface
for each session; up to 32 configured accounts and a .10-.99 IPv4 pool.
This is a configuration limit, not a guarantee of 32-client performance.
Authenticated clients can access LAN and use the router as an Internet
gateway. Public IPv4 reachability is
required; behind another router forward UDP 500/4500, and native ESP if
NAT traversal is not used. Plaintext L2TP/UDP 1701 is blocked by nftables.
Client must support L2TP/IPsec PSK with MS-CHAPv2 authentication.
VPN secrets are private runtime files, not prefilled in this image.

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
Also verify L2TP/IPsec from a separate external network with a compatible
client; build checks do not establish actual VPN interoperability.
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
on WAN ifup only for cudy,tr3600-v1. Existing Wi-Fi configuration is kept.
When generating a new 5 GHz radio, use channel 36, HE80 / 80 MHz and a
separate default SSID Cudy-TR3600-5G. Set country and a secure password
before enabling a fresh AP; no owner's wireless password is embedded.
The running user's router was repaired in place: gateway packet loss
fell from 40% to 0%; reported 5 GHz direct throughput was 284/50.7 Mbps,
and after returning to proxy mode 359/55 Mbps, with normal page opening.
These are user-reported measurements. A new image still requires the
complete build and packed-image verification before delivery.
