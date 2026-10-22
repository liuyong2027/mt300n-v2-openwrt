Cudy TR3600 V1.0 / R126 - SSR Plus+ 1.2.0 test2
Based on the tr3600-v1.1.1 device and application recipe.

Mango's proxy package, firewall helper and watchdog are removed from the image.
SSR Plus+ is the sole transparent proxy (nftables, Xray).
The exact helloworld revision is recorded in SOURCE.json.
A new Go package subtree is pinned separately for the matching Xray build.

ZeroTier private SS is retained with its existing LuCI page, approved private
network, port, cipher and password. It runs in a private network namespace.
Decrypted TCP and UDP re-enter the host through css-host, so SSR Plus+ applies
the same client routing rules as for ordinary clients. Never exclude this
interface/address from SSR Plus+ if it must use the proxy.
198.18.255.0/30 is reserved for this service. Existing overlapping routes cause
a closed failure instead of being changed. No private owner values are baked in.
Only the approved ZeroTier interface and /24 source subnet can reach the server.
Private SS pauses during SSR restarts. Disabling the selected SSR upstream
allows direct operation; stopping an enabled upstream does not select fallback.

Wi-Fi, USB/Samba, WebFiles, DDNS and ZeroTier device support are retained.
LED status now probes through SSR Plus+, independently of its failover timer.
Old Mango automatic failover history and per-node testing state are not copied.
Existing supported VLESS/SS/VMess node fields are translated once, preserving
the original private configuration for manual rollback in /etc/cudy-ssrplus/.
Check the migrated nodes and routing settings after boot.
No NaiveProxy/Cronet build is selected in this test profile.

Only flash on a matching Cudy TR3600 V1.0/R126 custom OpenWrt installation.
This sysupgrade file is not a stock-Cudy migration image.
Save a system backup and the current image before upgrading.
Do not force a device mismatch. Keep private SS and ZeroTier identity files
in the old firmware's backup archive before a keep-settings upgrade.
Verify SHA256SUMS. Build and QEMU checks do not replace hardware acceptance.
This test image has not been flashed or booted on your router.


Test2 fixes native-UCI compatibility in first-boot migration and the LED adapter.
It preserves a node selected after flashing when retrying an incomplete migration.
Packed-image verification now exercises the actual ARM64 UCI/nixio modules with
synthetic migration fixtures. Test1 users need the native-UCI fix; the original
test1 image alone may leave retired Mango DNS settings active.
