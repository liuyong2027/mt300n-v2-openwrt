# GL-MT300N-V2 OpenWrt 固件

Release 23 以 Release 22 为基础，修复 ZeroTier UPnP 规则因缺少外部 timeout 命令而未生成的问题，改用已有 ubus 的原生超时参数。其他运行功能和现有配置保持不变。

- [Release 23 固件及校验文件](https://github.com/liuyong2027/mt300n-v2-openwrt/releases/tag/v23.0.0)
- [发布说明](release23/RELEASE-23.md)
- [设备热修复验证记录](release23/DEVICE-HOTFIX-EVIDENCE-23.json)
- [历史 Release 22](https://github.com/liuyong2027/mt300n-v2-openwrt/releases/tag/v22.0.0)

构建入口为 release23/prepare.py：校验 Release 21 基础源包，精确重建并核验 Release 22 源包，再应用范围受限的 Release 23 修复，保留固定 OpenWrt/feeds 提交、软件包、内核、代理界面、分流、故障恢复及 ZeroTier 网关功能。

已在 Release 22 设备上验证相同辅助程序修复、重复刷新和防火墙重载，配置哈希及服务 PID 未变。Release 23 完整镜像仍需另行完成实机升级验收；本项目的编译和发布不会自动刷机。使用 LuCI 保留配置升级前先备份并核验 SHA256。
