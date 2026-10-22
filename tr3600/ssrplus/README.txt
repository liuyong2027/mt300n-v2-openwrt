Cudy TR3600 V1.0 / R126 - SSR Plus+ 1.2.0 test3
Based on the tr3600-v1.1.1 device and application recipe.

SSR Plus+ is the sole transparent proxy (nftables, Xray). Mango's proxy,
firewall helper and watchdog are removed. SOURCE.json records pinned sources.

SS servers are managed in SSR Plus+ > Server Settings. The Xray SS server
uses the selected ss_method, ss_password and ss_network fields. Access scope
is enforced by listener and firewall rules; public access requires an explicit
selection. New and unscoped configurations default to router-only access.
Unsupported ciphers or invalid SS2022 keys fail validation rather than being
silently replaced. The SS server list displays its cipher and access scope.

The old ZeroTier private SS entry is migrated once to the reserved SSR Plus+
server row cudy_zt_private. Port, password, cipher, enabled state and approved
ZeroTier interface/address/subnet/network ID are preserved. It still requires
both the server global switch and its row switch. Migration never turns on
the server global switch. The old cudy_ss config is retained as an inert
backup, not a second live credential source. The duplicate SS management
page and its old configuration-writing API are removed.
If private SS was never configured, it stays disabled without credentials or
approval. Its unified editing page requires an explicit connected private
ZeroTier IPv4 /24 selection for first approval; it never approves a network
automatically. The private page shares runtime port/password/cipher checks.

The private row runs internally in an isolated network namespace. Decrypted
TCP and UDP re-enter the host through css-host and use the same SSR Plus+
client policy. Do not exclude this interface/address from that policy.
198.18.255.0/30 is reserved internally; overlapping owner routes fail closed.
Only the approved ZeroTier interface and private /24 source subnet can reach
it. Missing approval, incomplete migration or invalid configuration closes
access. Private SS remains IPv4-only. This image does not claim complete
IPv6 transparent-proxy support.

Private SS pauses during SSR restarts. A selected but stopped upstream fails
closed; choosing no upstream explicitly allows direct operation. Existing
server/client/global configuration is preserved on retry. Private backup
files are kept on the router under /etc/cudy-ssrplus/ with restricted access.
No owner credentials or ZeroTier identity are included in this image.

Wi-Fi, USB/Samba, WebFiles, DDNS, ZeroTier and LED support are retained.
The built-in Dynu HTTPS DDNS provider bypasses SSR on its own curl sockets
while retaining WAN binding and certificate checks. Public IP detection,
encrypted provider DNS resolution and HTTPS updates use this path; ordinary
router traffic and other DDNS providers keep their existing policy.
Supported old Mango VLESS/SS/VMess node fields are translated once. Failover
history and per-node test state are not copied. Test2's native-UCI migration
and LED fixes are included. No NaiveProxy/Cronet build is selected.

Use only on a matching Cudy TR3600 V1.0/R126 custom OpenWrt installation.
This sysupgrade file is not a stock-Cudy migration image. Back up the system,
SS and ZeroTier configuration/identity before a keep-settings upgrade.
Verify SHA256SUMS, and do not force a device mismatch. BUILD-VERIFICATION.json
states the actual build and software test scope. Build/QEMU/network-namespace
checks do not replace hardware acceptance. This image has not been flashed
or booted on your router by the build process.
