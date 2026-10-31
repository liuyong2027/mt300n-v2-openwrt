# GL-MT300N-V2 OpenWrt 固件

Release 25 在 Release 24 基础上增加 **IKEv2 客户端构建配置**。默认 `standard` 仍是 Xray 版；`ikev2` 用 strongSwan 替换 Xray（16 MiB 闪存互斥），支持国内 IP 分流、防污染 DNS，以及按 GFW 域名列表分流。

- [Release 25 说明](release25/RELEASE-25.md)
- [Release 24 固件及校验文件](https://github.com/liuyong2027/mt300n-v2-openwrt/releases/tag/v24.0.0)
- [Release 24 发布说明](release24/RELEASE-24.md)
- [历史 Release 23](https://github.com/liuyong2027/mt300n-v2-openwrt/releases/tag/v23.0.0)

构建入口：

```bash
python3 release25/prepare.py
cd source25
# Xray 默认镜像
bash scripts/prepare.sh
# 或 IKEv2 客户端镜像
MANGO_BUILD_PROFILE=ikev2 bash scripts/prepare.sh
```

刷机前备份并核验 SHA256。固件不包含用户节点、密钥或运营商凭据。
