Cudy TR3600 V1.0 / R126 - SSR Plus+ 1.2.0 test4
Based on the tr3600-v1.1.1 device and application recipe.

SSR Plus+ is the sole transparent proxy (nftables, Xray). SOURCE.json records
pinned sources. Wi-Fi, USB/Samba, WebFiles, DDNS, ZeroTier and LED remain.

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
