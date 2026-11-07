TR3600 1.3.0 — SSR Plus+ + IKEv2 dual-stack

Build: push to codex/tr3600-1.3.0-ikev2 (paths tr3600/** or this workflow),
or workflow_dispatch on .github/workflows/tr3600-ssrplus.yml.

Recipe changes vs 1.2.0:
- package tr3600/luci-app-mango-ikev2 (Release 26 hotfixes, TR3600-adapted)
- profile.py selects strongSwan + luci-app-mango-ikev2 alongside SSR Plus+
- runtime exclusive egress via mango-ikev2-peer-engine (stops shadowsocksr)
- cudy-release = tr3600-ssrplus-ikev2-1.3.0
