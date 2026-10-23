include $(TOPDIR)/rules.mk
LUCI_TITLE:=Cudy USB sharing with remembered disk consent
LUCI_DEPENDS:=+lua +libuci-lua +luci-lib-nixio +luci-lib-jsonc +flock +coreutils-timeout +block-mount +samba4-server
LUCI_PKGARCH:=all
PKG_LICENSE:=MIT
include $(TOPDIR)/feeds/luci/luci.mk
# call BuildPackage - OpenWrt buildroot signature
