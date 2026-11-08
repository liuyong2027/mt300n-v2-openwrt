mac80211-f0a60eee.uc is an unmodified OpenWrt wireless generator fixture.
Source: OpenWrt v25.12.5 commit f0a60eee2fe051741c643ea6118718aae1ef17fb
Path: package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc
Git blob: d61786fa65023521d16fdf6bc499c2d26ee2d275
https://github.com/openwrt/openwrt/blob/f0a60eee2fe051741c643ea6118718aae1ef17fb/package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc
mac80211-64900e75.uc is the same unmodified generator at OpenWrt v25.12.6
commit 64900e756efa667774214f9c6b17c113222e01f7.
Git blob: c6c973040eb8c01f8fb8618337f9d1cf3cce4447
https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc
The only difference is upstream 6bc29f34241d (wifi-scripts: add 60G band to
mac80211.uc to support 802.11ad), which changes one line to
const bands_order = [ "60G", "6G", "5G", "2G" ];
License: GPL-2.0, as declared by OpenWrt package/network/config/wifi-scripts/Makefile.
This regression fixture accesses no live wireless configuration or router.
USB integration fixture: samba-5caa62e0.init is the unmodified OpenWrt
packages net/samba4/files/samba.init at locked feed commit
5caa62e0bc9f7fb9b0c12a23267bceb7724214dd (Git blob
468ba553a2b87ba3cb8d1ca2b9f638f820764a3d), retained under upstream terms.
Source: https://github.com/openwrt/packages/blob/5caa62e0bc9f7fb9b0c12a23267bceb7724214dd/net/samba4/files/samba.init
