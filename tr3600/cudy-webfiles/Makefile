include $(TOPDIR)/rules.mk
PKG_NAME:=cudy-webfiles
PKG_VERSION:=0.6.3
PKG_RELEASE:=1
PKG_LICENSE:=MIT Apache-2.0 BSD-3-Clause
include $(INCLUDE_DIR)/package.mk

# Go already builds both binaries with -s -w. rstrip/sstrip changes their
# bytes after manifest hashes are recorded, breaking installation validation.
# Preserve exact source-built bytes; the final packed-image hash gate remains.
RSTRIP:=:

define Package/cudy-webfiles
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=File Transfer
  TITLE:=Cudy WebFiles guarded HTTPS file service
  DEPENDS:=+lua +libuci-lua +luci-lib-nixio +luci-lib-jsonc +luci-app-cudy-usb +firewall4 +rpcd +ca-bundle
endef

define Package/cudy-webfiles/conffiles
/etc/config/cudy_webfiles
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)
	test -s ./build-output/cudy-webfiles
	test -s ./build-output/filebrowser
	test -s ./build-output/manifest.json
endef

define Build/Compile
endef

define Package/cudy-webfiles/install
	$(CP) ./root/. $(1)/
	$(INSTALL_DIR) $(1)/usr/lib/cudy-webfiles/bin
	$(INSTALL_BIN) ./build-output/cudy-webfiles $(1)/usr/lib/cudy-webfiles/bin/
	$(INSTALL_BIN) ./build-output/filebrowser $(1)/usr/lib/cudy-webfiles/bin/
	$(INSTALL_DATA) ./build-output/manifest.json $(1)/usr/lib/cudy-webfiles/
	chmod 755 $(1)/etc/init.d/cudy-webfiles $(1)/etc/uci-defaults/98-cudy-webfiles $(1)/usr/libexec/rpcd/cudy.webfiles
endef

$(eval $(call BuildPackage,cudy-webfiles))
