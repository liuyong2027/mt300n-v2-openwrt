include $(TOPDIR)/rules.mk
LUCI_TITLE:=Cudy private ZeroTier Shadowsocks server
LUCI_DEPENDS:=+luci-app-mango-proxy +lua +libuci-lua +luci-lib-nixio +luci-lib-jsonc +flock +coreutils-timeout +zerotier +firewall4
LUCI_PKGARCH:=all
PKG_LICENSE:=MIT
include $(TOPDIR)/feeds/luci/luci.mk
# call BuildPackage - OpenWrt buildroot signature
