Cudy TR3600 V1.0 - 1.0.0 release build

Only for Cudy TR3600 V1.0 (cudy,tr3600-v1 / R126).
This is a community custom firmware, not a Cudy vendor firmware release.
Read RELEASE-NOTES.txt for accepted RC1 tests and the limits of this image.
Build proof, source commit and image SHA256 are in tr3600-verification.json.
A successful build does not mean this new image has already been installed.

Locked sources: application 1f6169759396a31d2e3beec35d300c1fe4f2eaec;
OpenWrt 25.12.5 f0a60eee2fe051741c643ea6118718aae1ef17fb and locked feeds.
Mango UI, R3 Xray patch, subscriptions, failover and ZeroTier are retained.
The upstream application keeps its 20-test-failover1 marker for provenance;
/etc/cudy-release identifies this device firmware as tr3600-1.0.0.
OpenWrt Filogic kernel defaults and XZ SquashFS with 1 MiB blocks are retained.

Included:
- Private ZeroTier SS server under Services / SS 服务端. AES-128-GCM,
  AES-256-GCM or ChaCha20-Poly1305; TCP/UDP follow existing proxy routing.
  Default disabled, no prefilled credentials or personal network IDs.
  First enable requires exactly one eligible private ZeroTier IPv4 /24 and
  explicit confirmation of the displayed scope. Set a 24-128 byte secret.
  Existing scope is not changed automatically. Only approved ZeroTier
  interface/subnet traffic is accepted; no WAN access is enabled.
  Valid guard checks no longer take the proxy operation lock. Repairs still
  require locking, rechecking and validation before changing rules.
- USB: Services / Network Shares / USB 文件共享. Select a partition, share
  name and read-only/read-write access, then explicitly enable sharing.
  UUID authorization is remembered; reinsertion restores the share.
  FAT, exFAT, ext4, NTFS3, USB storage and UAS drivers are included.
  Guests on LAN receive the selected access to the authorized partition.
  No automatic formatting, filesystem repair or recursive permission changes.
  Safely unmount every partition before unplugging. Missing per-share
  metadata is recreated; duplicate UUIDs and invalid mounts are rejected.
- Optional dual-band unification in Network / Wireless / Wi-Fi 双频合一.
  Select two enabled LAN APs and shared SSID/security/password. Optional
  local usteer suggests 5 GHz to supported clients; clients decide whether
  to switch. Default disabled; disabling restores backed-up AP settings.
  New APs remain disabled until the owner sets country and security.
  New 5 GHz configuration defaults to channel 36/HE80.
- Client/AP repeater and IPv4 relayd pseudo bridge through normal LuCI.
  Routed repeater LAN and upstream should use different subnets.
- Recommended white/red LED status, optional night schedule off by default.
  White solid: recent success; white slow: waiting; red solid: no local exit;
  red slow: repeated upstream/proxy failure. Ordinary LAN or unrelated USB
  events do not reset the exit identity.
- WAN/LAN EEE and Tx LPI workaround, PPP/PPPoE, Samba4 and full wpad.

L2TP/IPsec server and Dynamic DNS remain excluded. Upgrade migration privately
backs up retired configuration and removes only project-owned VPN rules.
Cudy vendor UI, App, cloud management and Mesh are not included.

Upgrade from a matching custom TR3600 OpenWrt image:
1. Back up settings and retain the previous image locally.
2. Connect by LAN cable and verify the image against SHA256SUMS.
3. Upload sysupgrade.bin under LuCI System / Backup / Flash Firmware.
   Keep settings to retain network, proxy, SS, ZeroTier and USB authorization.
   Never force an upgrade that reports a device mismatch.
4. Wait for reboot, then check the version and your proxy/SS/USB/LED functions.
   A source commit or build never upgrades the running router automatically.

From stock Cudy firmware:
1. Confirm TR3600 V1.0 and save original settings.
2. Obtain the official Develop_files_for_TR3600.zip and follow its README:
   https://www.cudy.com/zh-cn/pages/download-center/tr3600-1-0
3. Follow its Intermediate firmware/ cudy_tr3600-v1-sysupgrade_260715.bin
   migration procedure before installing this OpenWrt sysupgrade image.
4. Do not keep vendor/intermediate settings during that migration. Fresh LAN
   is http://192.168.8.1 . Set the administrator password and Wi-Fi security.

The TR3600-only dual-slot helper validates slot names, writes both inactive
volumes and then changes boot variables. Shared rootfs_data is recreated and
selected configuration restored; automatic rollback is not guaranteed.
Bootloader, Factory and bdinfo are not written by this helper.
Hardware corrections retain PWM0/GPIO13 fan, GPIO6 supply, red GPIO46,
white GPIO48, radio MAC offsets base+0/base+16 and active thermal maps.
Device sources: https://github.com/openwrt/openwrt/pull/24596
https://github.com/hyqhyq3/openwrt-cudy-tr3600/blob/main/cudy-tr3600-v1-fixes.patch
Vendor dual-image support originates from the official development ZIP.
Upstream and bundled sources retain their original licenses.
Source documentation: USB-SHARING.md, WIFI-UNIFICATION.md and LED-STATUS.txt.
