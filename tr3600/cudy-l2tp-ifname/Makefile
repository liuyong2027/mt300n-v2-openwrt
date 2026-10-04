include $(TOPDIR)/rules.mk
PKG_NAME:=cudy-l2tp-ifname
PKG_VERSION:=1
PKG_RELEASE:=1
PKG_LICENSE:=MIT
PKG_BUILD_DEPENDS:=ppp
include $(INCLUDE_DIR)/package.mk

define Package/cudy-l2tp-ifname
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=VPN
  TITLE:=Separate PPP interface for each L2TP VPN client
  DEPENDS:=+ppp
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/*.c $(PKG_BUILD_DIR)/
endef

define Build/Compile
	$(TARGET_CC) $(TARGET_CFLAGS) $(TARGET_CPPFLAGS) -fPIC -shared -Wall -Wextra \
		-o $(PKG_BUILD_DIR)/cudy-l2tp-ifname.so $(PKG_BUILD_DIR)/ifname.c $(TARGET_LDFLAGS)
endef

define Package/cudy-l2tp-ifname/install
	$(INSTALL_DIR) $(1)/usr/lib
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/cudy-l2tp-ifname.so $(1)/usr/lib/
endef

$(eval $(call BuildPackage,cudy-l2tp-ifname))
