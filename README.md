# GL-MT300N-V2 定制 OpenWrt 固件

**Release 22（v22.0.0）** 以 [Release 21](https://github.com/liuyong2027/mt300n-v2-openwrt/releases/tag/v21.0.0) 为基础，增加 ZeroTier UDP 直连与 UPnP 发现响应规则。仅适用于 **GL.iNet GL-MT300N-V2**。

- [Release 22 发布页与下载](https://github.com/liuyong2027/mt300n-v2-openwrt/releases/tag/v22.0.0)
- [完整更新与升级说明](release22/RELEASE-22.md)
- [构建和验证流程](.github/workflows/release22.yml)
- [Release 21 历史说明](RELEASE-21.md)

## ZeroTier 规则

`ZeroTier direct UDP` 放行 WAN 到本机三个明确配置的 ZeroTier UDP 监听端口；`ZeroTier UPnP discovery` 仅允许当前 IPv4 WAN 上级网关从 UDP 源端口 1900 返回发现响应。它们由专属 nftables 链维护，在开机、防火墙重载、WAN 上下线或更新，以及 ZeroTier 启停时刷新，带有可核对的规则注释。

已有 local.conf 路径和内容保持不变。没有 local.conf 时，固件新增持久配置，将第二、第三端口固定为 48170 和 20089；主端口遵循原 UCI 设置，默认 9993。已有自定义配置若没有固定三个端口，辅助程序会保留配置并记录原因，不猜测随机端口。显式禁用的专属 include 保持禁用。

## 功能和配置保留

沿用 Release 21 的依赖版本、普通版内核、代理核心与界面、分流和 DNS、故障切换与恢复保护、ZeroTier 网关。升级初始化脚本保护已有防火墙段、语言和 Wi-Fi LED 设置。源码差异和哈希见发布附件 `SOURCE-DELTA-22.json`。

备份配置、核对型号和 SHA256 后，使用 `mt300n-v2-22-production-sysupgrade.bin`。已有本项目固件可选择保留配置升级。构建和发布不会自动刷写设备；新完整镜像实机升级、重启及跨公网直连验收仍待完成，历史硬件记录不代表新镜像实机验收。实际直连效果取决于上游 NAT、防火墙和对端。

## 可复现的源码入口

`release21-source.zip.b64` 是锁定的基线；`release22/overlay/` 保存可审查的增量文件。运行 `python3 release22/prepare.py` 会校验基线和逐文件清单，在新目录 `source22/` 中生成完整 Release 22 源码、差异清单和源码包。后续 Linux 构建、原有回归、真实 nftables UDP 测试、实际 MIPS 验证和发布门禁均由工作流执行。

本仓库其他分支或发布中的 Cudy TR3600 镜像不适用于 GL-MT300N-V2。
