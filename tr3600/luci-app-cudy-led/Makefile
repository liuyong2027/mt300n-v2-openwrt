include $(TOPDIR)/rules.mk
LUCI_TITLE:=Cudy network and proxy status LEDs
LUCI_DEPENDS:=+lua +libuci-lua +luci-lib-nixio +luci-lib-jsonc +flock +curl +ca-bundle +coreutils-timeout
LUCI_PKGARCH:=all
PKG_LICENSE:=MIT
include $(TOPDIR)/feeds/luci/luci.mk
# call BuildPackage - OpenWrt buildroot signature
