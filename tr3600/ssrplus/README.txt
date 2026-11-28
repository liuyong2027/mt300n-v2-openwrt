Cudy TR3600 V1.0 / R126 - SSR Plus+ and IKEv2 1.3.6 candidate
Based on the tr3600-v1.3.5 device and application recipe.

The candidate is awaiting hardware acceptance. Its internal version is
tr3600-ssrplus-ikev2-1.3.6. Use SHA256SUMS to identify the exact checked image.

To tune an Xray Hysteria2 node, open SSR Plus+ > Node List and edit the node.
UDP Receive Buffer and UDP Send Buffer each accept a request from 1 to 16 MiB.
A blank field lets Xray manage that buffer. Linux normally reports twice the
requested value. Each setting belongs to the node where it is entered.

The IKEv2 primary, backup 1 and backup 2 each accept their own remote UDP port.
A blank port uses standard IKEv2 ports. The certificate uploader accepts PEM
and DER and replaces the installed root CA. Keep-settings upgrades migrate the
legacy file to ikev2-root-ca.pem. The status shows the certificate subject,
expiration and whether strongSwan has loaded that exact certificate.

SSR Plus+ (nftables, Xray) and IKEv2 run as mutually exclusive proxy modes.
SOURCE.json records pinned sources. Wi-Fi, USB/Samba, WebFiles, DDNS,
ZeroTier and LED remain available.

Dual-band Wi-Fi unification remains available. Automatic band steering defaults
off in both the UCI configuration and LuCI checkbox; enabling a shared SSID does
not enable steering automatically. Owners may opt in to steering separately.
Keep-settings upgrades retain saved Wi-Fi and steering choices. No upgrade or
startup migration replaces an existing owner choice with this fresh default.

The validated YAML node importer is included in this image. One subscription
can contain AnyTLS, VMess and Hysteria2; supported connection parameters are
mapped to ordinary Xray nodes. HTTP/inline proxy-providers are supported.
Existing SSR policy and DNS remain in control. YAML rules, groups, DNS, TUN
and listeners are not applied. Unsupported connection parameters reject the
whole affected subscription group and preserve its previous nodes.

The subscription User-Agent field offers Mihomo (mihomo/1.18.0), alongside
the existing suggestions and manual input. A saved UA is never replaced by
this addition. Default notice filters include 邮箱客服 and 支持AI. Fresh
settings, SSR reset and the missing-value fallback use the same defaults.
On upgrade, only the exact old default filter list is extended automatically;
custom owner lists, including an existing AI keyword, are retained.

The server list includes a leftmost numbered column. Numbers continue across
pages (the second 50-row page starts at 51) and follow the displayed row order
immediately after dragging. They are display positions; stored node identities,
names, selected node and automatic switch order are not changed by numbering.

Node rows offer individual checkboxes and Select all on this page. Delete
selected nodes confirms the count and submits one authenticated POST request.
Nodes referenced by main/UDP/SOCKS/HTTP settings are protected. The complete
selection is validated before a single native UCI commit without a service
reload notification. Pending SSR edits must be applied or discarded first. Selection
is display-only and is cleared on page reload. Subscription updates can restore
deleted subscription nodes; use subscription filters for permanent exclusions.

Fresh defaults leave Forced proxy WAN IPs, Direct domains (white.list), and
Blocked domains (deny.list) empty. Keep-settings upgrades retain saved owner
configuration and list files; no startup migration clears them. The forced
proxy domain list and internal SS bypass network are outside this change.

Ordinary SS is managed in SSR Plus+ > Server Settings. Existing ss_method,
ss_password, ss_network and Access Scope are preserved. Enabled ordinary SS
rows share one supervised Xray in an isolated network namespace. Decrypted
TCP and UDP enter the existing SSR client policy through css-host. Routing
mode, bypass/proxy lists, selected ports and a UDP-capable upstream determine
each flow. Encrypted replies bypass recapture. SS no longer depends on router
OUTPUT interception for decrypted traffic.

Access Scope controls encrypted ingress: router loopback only, active LAN
IPv4 interface/address only, or explicit public access. Only selected TCP/UDP
transports are admitted. Missing LAN details close LAN network access. Direct
access to the internal peer is blocked. Overlaps with internal 198.18.255.0/30
and existing host listeners fail closed. Seven AEAD/SS2022 methods are supported;
unsupported methods/keys fail validation. SS ingress remains IPv4-only.
The upstream IPv6 proxy options are separate and retain their existing scope.

Access Scope applies to every built-in server type. The traffic explanation
changes immediately with Server Type: only ordinary Shadowsocks describes
the SSR client TCP/UDP policy path; SOCKS5, VMess and the other host server
types describe the router's own outbound policy. These notes are display-only.
The Local Servers indicator excludes watcher/client processes and checks
ordinary SS readiness or an owned host-server listener before showing Running.

The dedicated ZeroTier private SS is DELETED, not migrated. First boot removes
its reserved server row, /etc/config/cudy_ss, private approval/credential files
and dedicated firewall sections. Private passwords/ports/approval are not copied
to ordinary SS. The duplicate page, management API and private runtime are absent.
Shared internal namespace helpers now serve ordinary SS only.

ZeroTier identity/networks and its independent UDP communication and gateway
UPnP discovery firewall rules remain. A keep-settings upgrade retains ordinary
SS, client nodes/subscriptions, global settings, Wi-Fi, DDNS and ad-list settings.
An upgrade without keeping settings cannot retain owner settings. No owner
credentials or ZeroTier identity are embedded in this image.

SS outbound pauses during SSR restarts. A selected but stopped relay fails
closed; selecting no relay explicitly permits direct operation. Changes to
scope, transport or enable state restart the shared SS core to revoke sessions.

Dynu HTTPS DDNS retains the direct marked-socket path, WAN binding and TLS
certificate checks. Other router/DDNS traffic keeps its policy. Test3 startup,
native-UCI, LED and enhanced-Xray protocol fixes remain.

Use only on a matching Cudy TR3600 V1.0/R126 custom OpenWrt installation.
This is not a stock-Cudy migration image. Back up settings and ZeroTier identity,
verify SHA256SUMS, and never force a device mismatch. BUILD-VERIFICATION.json
states build/software test scope. Namespace/QEMU checks do not replace hardware
acceptance. Building this image does not flash or reboot your router.
