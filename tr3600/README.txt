Cudy TR3600 V1.0 - 1.1.1 WebFiles + DDNS stable release

Only for Cudy TR3600 V1.0 (cudy,tr3600-v1 / R126).
This is a community custom firmware, not a Cudy vendor firmware release.
Read RELEASE-NOTES.txt for prior baseline tests and the limits of this image.
Build proof, source commit and image SHA256 are in tr3600-verification.json.
A successful build does not mean this new image has already been installed.

Locked sources: application 1f6169759396a31d2e3beec35d300c1fe4f2eaec;
OpenWrt 25.12.5 f0a60eee2fe051741c643ea6118718aae1ef17fb and locked feeds.
Mango UI, R3 Xray patch, subscriptions, failover and ZeroTier are retained.
The upstream application keeps its 20-test-failover1 marker for provenance;
/etc/cudy-release identifies this device firmware as tr3600-1.1.1.
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
  to switch. Both unification and steering default off; steering can be enabled
  separately. Disabling unification restores backed-up AP settings.
  New APs remain disabled until the owner sets country and security.
  New 5 GHz configuration defaults to channel 36/HE80.
- Client/AP repeater and IPv4 relayd pseudo bridge through normal LuCI.
  Routed repeater LAN and upstream should use different subnets.
- Recommended white/red LED status, optional night schedule off by default.
  White solid: recent success; white slow: waiting; red solid: no local exit;
  red slow: repeated upstream/proxy failure. Ordinary LAN or unrelated USB
  events do not reset the exit identity.
- WAN/LAN EEE and Tx LPI workaround, PPP/PPPoE, Samba4 and full wpad.

Included WebFiles and DDNS:
- Cudy webpage WebFiles 0.6.6: LuCI start/stop, up to16 independent users,
  per-user write permission, HTTPS, optional ZeroTier and public gateway.
  Fresh service/read-write/ZeroTier/public access are disabled. No personal
  volume, account, CA, DDNS domain or network ID is preconfigured. LAN port8080.
- Standard LuCI Dynamic DNS and provider definitions including Dynu.
  Existing DDNS configuration and enabled-service links are preserved.
- WebFiles encrypted account key/accounts/TLS directory is included in the
  sysupgrade keep list. Existing owner settings take precedence over defaults.

PPTP and L2TP/IPsec server remain excluded. Upgrade migration privately backs
up only the obsolete L2TP configuration and removes only its owned VPN rules.
This new full1.1.1 image has not been flashed or hardware accepted.
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


ZeroTier direct-path fixes from the 2026-10-16 diagnostic are integrated:
- Pin secondary/tertiary UDP ports on a fresh installation; use the actual
  configured primary port. Preserve an existing local.conf without rewriting it.
- Accept only these UDP ports in fw4 input_wan; SSDP replies only from the
  current WAN default gateway, UDP source1900 to high ports. No private gateway,
  personal network ID, node identity or public mapping port is baked in.
- Reconcile this helper's owned nft chain after firewall reload, WAN changes,
  and ZeroTier start/stop. No proxy restart, timer loop or global firewall flush.
- Preserve /etc/zerotier-stable-ports.json in subsequent settings upgrades.
  IMPORTANT for the FIRST upgrade from older firmware: the old firmware selects
  backup paths. Before flashing, add /etc/zerotier-stable-ports.json and
  /etc/cudy-webfiles/ to its /etc/sysupgrade.conf, and verify they are in the
  backup archive. This build does not modify or flash the running router.
- Keep existing owner firewall rules. Low-bandwidth mode is not enabled.
  The optional small-ping trial on6.1 was not made permanent. This firmware
  does not claim to remove remote signature-verification delays or ensure
  DIRECT under all NAT/firewall conditions. New-image hardware testing pending.


Packaging revision r2 preserves the exact Go -s/-w executable bytes instead of
running OpenWrt rstrip/sstrip again after the manifest hashes are calculated.
The packed-image binary/hash comparisons remain mandatory and unchanged.
Settings upgrades preserve existing Mango firewall sections, including zone
policies, NAT scopes and disabled DNS/gateway rules. A fresh mangozt zone keeps
the owner-selected defaults: input/output/intra-zone forward ACCEPT, IPv4 masq1.

1.1.1 restores a preserved WebFiles private directory from0755 to0700 only
after validating its root ownership, public marker and every private file.
Encrypted accounts, keys and all TLS slots are retained without replacement.
The initializer runs before service enable and before the service reset.
Missing directories are left absent; abnormal ownership, permissions, links
and writable directories are rejected. Existing binary guards remain strict.
Actual ARM64 tests cover11 cases, including real tar file-list restoration,
before the full build and again against the final packed filesystem.
Download name: cudy-tr3600-v1-1.1.1-sysupgrade.bin.
The rc2 router required one manual directory-mode correction before its LAN,
ZeroTier and public phone acceptance passed. This prior evidence does not
replace keep-settings upgrade and client acceptance of this new1.1.1 image.
No WAN/PHY/proxy change is included; previous spontaneous link flaps and the
known FAT32 dirty-unmount condition are not claimed fixed.

1.1.1 retains the bounded initial boot readiness and root-only early startup
diagnostics accepted with WebFiles0.6.4 on rc3. WebFiles0.6.6 adds certificate
changes accepted as a component on the current1.1.0 router, without another
whole-router reboot. The full image is a new build;
its own upgrade/boot/client hardware acceptance has not been performed.
Release1.1.1 is published as a normal GitHub release at the owner request.
No real device is flashed by this workflow. WAN flaps/FAT32 remain unresolved.

1.1.1 adds365-day formal CA names for newly generated certificates, retaining
existing TLS slots. Dynu HTTPS uses a WAN-bound public-IP source and scoped
encrypted DNS, with credential-preserving IPv4 migration. Other providers,
IPv6 and custom updaters are not migrated. Full-image hardware acceptance pending.

1.1.1 also includes the accepted LED connectivity ownership fix. LED probes
when failover is off; proxy-mode failover supplies observations when enabled.
Direct mode always uses LED probes. Both callers share one bounded HTTP/TLS
script installed with the proxy package. Original failover decisions stay unchanged.
Source changes discard stale observations; the complete image is not boot accepted.
