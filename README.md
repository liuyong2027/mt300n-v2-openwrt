# GL-MT300N-V2 OpenWrt 固件

- [Release 25 IKEv2 热修复说明](release25/RELEASE-25.md)（相对已刷入的 IKEv2 profile=25 的实机热修复汇总；不含完整 sysupgrade）
- [Release 24](https://github.com/liuyong2027/mt300n-v2-openwrt/releases/tag/v24.0.0)
- [Release 23](https://github.com/liuyong2027/mt300n-v2-openwrt/releases/tag/v23.0.0)

Release 23 以 Release 22 为基础，修复 ZeroTier UPnP 规则因缺少外部 timeout 命令而未生成的问题，改用已有 ubus 的原生超时参数。其他运行功能和现有配置保持不变。

构建与历史说明见各 eleaseNN/ 目录。
