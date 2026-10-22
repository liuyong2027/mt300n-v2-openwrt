GL-MT300N-V2 Release 23 SSR Plus+ capacity trial

Base recipe: be09bd22535c598a0e9a093edfeabb2393aeced0
OpenWrt: f0a60eee2fe051741c643ea6118718aae1ef17fb (25.12.5)
SSR Plus+: fw876/helloworld 2abdc9aa9e19607774dc9789709212b70b8607c6
Xray: baseline 26.3.27 with the existing Vision/UDP443 patch.
Purpose: build and measure only. No release publication, merging or device flashing.

One proxy core binary, Xray, with VLESS REALITY/Vision, VMess raw/WS with optional TLS,
ordinary Shadowsocks, Trojan and SOCKS/HTTP paths provided by that Xray version.
No SSR protocol engine, sing-box, Mihomo, V2Ray core, Hysteria standalone core or server core.

Retained unchanged: ZeroTier identity/network configuration/local.conf and the Release 23
native ubus timeout fix, owned UDP/UPnP rules, gateway defaults and hotplug/init integration.
The helper remains under /usr/lib/mango for compatible existing firewall includes.

Mango UCI is preserved as the original file and in migration backup, not included in public artifacts.
On a future owner-approved settings upgrade, legacy VLESS/VMess/SS nodes, active configured node,
ordered backups, enabled/disabled failover, direct/split/global/GFW mode, extra bypass IPv4,
direct domains, subscription URL and optional SOCKS TCP port are converted.
Only the old Mango DNS target and owned proxy include are retired.
An existing native SSR Plus+ node configuration has priority. Migration is idempotent.
Validation failure restores the original destination files. No secrets are printed.
SSR Plus+ replaces Mango's runtime and its switching behavior; their recovery algorithms differ.

Memory: GOMEMLIMIT=48MiB and GOMAXPROCS=1; TCP/UDP and local SOCKS use the same active Xray.
The standalone ssr-check is compiled from upstream's libc-only source, avoiding unused SSR
crypto library dependencies. No protocol functionality is obtained from this check program.
One process additionally supports direct-mode SOCKS only while the main proxy is disabled.
Native LuCI changes to uncommon features require their dependencies; they are not installed.

Build: python3 release23/prepare.py; python3 trial/transform.py source23
cd source23; bash scripts/prepare.sh
python3 scripts/kernel-profile.py configure --tree openwrt --profile production
make -C openwrt defconfig
make -C openwrt download -j4
make -C openwrt -j4 V=s
python3 ../trial/verify.py .
The original 8a969945 capacity image was flashed on 2026-10-22. On-device
compatibility fixes below passed node, traffic, DNS, ZeroTier and LuCI checks.
The original image does not include these fixes; a new capacity build is required.

On-device corrections, 2026-10-22:
Use nixio symbolic file modes and native UCI cursor:set section creation.
Reference immutable SquashFS defaults when backing up migration inputs.
Include luci-compat; load actual runtime Lua dependencies before generator fixtures.
Serialize init actions with a stable lock inode; prevent daemon lock inheritance.
Use numeric nft dumps and quote logger messages. Real node migration and traffic
acceptance are recorded separately from the original capacity-only build.
