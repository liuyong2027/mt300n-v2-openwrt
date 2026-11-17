TR3600 1.3.3 — EAP secret load and SSR lock release

Base: the 1.3.2 candidate on cursor/tr3600-ikev2-dns-1.3.2-dc6c.
OpenWrt 25.12.6. cudy-release = tr3600-ssrplus-ikev2-1.3.3.
luci-app-mango-ikev2 PKG_RELEASE is 3.

swanctl --load-creds --noprompt --file points at the generated
swanctl.conf before --load-conns. SSR restart from failover closes fd 9.
