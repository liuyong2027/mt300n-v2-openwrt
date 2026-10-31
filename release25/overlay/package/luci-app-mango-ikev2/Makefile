include $(TOPDIR)/rules.mk

LUCI_TITLE:=Mango IKEv2 client with China split routing
LUCI_DEPENDS:=+strongswan-minimal +strongswan-swanctl +strongswan-mod-eap-mschapv2 +strongswan-mod-eap-identity +strongswan-mod-eap-dynamic +strongswan-mod-openssl +strongswan-mod-pem +strongswan-mod-pkcs1 +strongswan-mod-x509 +kmod-xfrm-interface +kmod-ipsec4 +ip-full +curl +ca-bundle +lua +libuci-lua +flock
LUCI_PKGARCH:=all
PKG_LICENSE:=MIT

include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature
