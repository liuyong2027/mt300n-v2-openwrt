include $(TOPDIR)/rules.mk

PKG_NAME:=cudy-ddns-direct
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)-$(PKG_VERSION)

include $(INCLUDE_DIR)/package.mk

define Package/cudy-ddns-direct
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Scoped Dynu DDNS direct sockets for SSR Plus+
  DEPENDS:=+curl
endef

define Package/cudy-ddns-direct/description
 Mark only the Dynu DDNS curl subprocess sockets with SSR's existing direct
 mark 255, preserving WAN binding and HTTPS certificate verification.
endef

define Build/Prepare
	$(call Build/Prepare/Default)
	$(CP) ./src/* $(PKG_BUILD_DIR)/
endef

define Build/Compile
	$(TARGET_CC) $(TARGET_CPPFLAGS) $(TARGET_CFLAGS) -Wall -Wextra -Werror -fPIC -shared \
		-o $(PKG_BUILD_DIR)/socket-mark.so $(PKG_BUILD_DIR)/socket-mark.c $(TARGET_LDFLAGS) -ldl
	$(TARGET_CC) $(TARGET_CPPFLAGS) $(TARGET_CFLAGS) -Wall -Wextra -Werror \
		-o $(PKG_BUILD_DIR)/cudy-ddns-direct $(PKG_BUILD_DIR)/launcher.c $(TARGET_LDFLAGS) -ldl
endef

define Package/cudy-ddns-direct/install
	$(INSTALL_DIR) $(1)/usr/lib/cudy-ddns-direct $(1)/usr/libexec $(1)/etc/uci-defaults
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/socket-mark.so $(1)/usr/lib/cudy-ddns-direct/socket-mark.so
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/cudy-ddns-direct $(1)/usr/libexec/cudy-ddns-direct
	$(INSTALL_BIN) ./files/cudy-ddns-curl $(1)/usr/libexec/cudy-ddns-curl
	$(INSTALL_BIN) ./files/80-cudy-ddns-direct $(1)/etc/uci-defaults/80-cudy-ddns-direct
endef

$(eval $(call BuildPackage,cudy-ddns-direct))
