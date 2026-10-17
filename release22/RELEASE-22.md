# Release 22 — GL-MT300N-V2 · ZeroTier 直连规则

以正式版 Release 21（v21.0.0）为基础，仅适用于 GL.iNet GL-MT300N-V2。

## 本次增加

- `ZeroTier direct UDP`：在 WAN 输入链放行本机 ZeroTier 的三个明确配置的 UDP 监听端口。
- `ZeroTier UPnP discovery`：仅接受当前 IPv4 WAN 上级网关、UDP 源端口 1900 到本机高位端口的发现回复；网关变化后替换旧规则。
- 通过独立 nftables 链维护运行规则，支持开机、防火墙重载、WAN 上下线与地址/路由更新，以及 ZeroTier 启停。维护只清理自身拥有的链和跳转。
- 已有 ZeroTier local.conf 路径和内容保持不变。未配置 local.conf 时新增持久配置，将第二、第三端口固定为 48170 和 20089；主端口沿用 UCI 设置，缺省为 9993。已有自定义配置若未固定三个端口，辅助程序保留原配置并记录原因，不猜测随机端口。
- ZeroTier 默认启用状态、身份密钥、网络 ID、代理节点与策略、无线和现有防火墙配置保留。旧初始化脚本仅在相应配置不存在时写入默认防火墙段、Wi-Fi LED 和界面语言。

## 保留的功能

沿用 Release 21 的 OpenWrt 与 feeds 固定提交、普通版内核、代理核心和界面、DNS/分流、自动故障切换、恢复保护和 ZeroTier 网关功能。`SOURCE-DELTA-22.json` 列出所有源码变化及基线校验值。

## 验证与限制

发布要求通过原有 Linux 回归、MIPS Xray、目标 BusyBox、内核配置和镜像格式检查，并增加配置保留、ZeroTier 生命周期、规则所有权、动态网关、真实 nftables UDP 收发和 MIPS Lua 策略测试。最终结果、大小和 SHA256 见 `BUILD-VERIFICATION.json` 和 `SHA256SUMS`。

本次构建及发布不连接设备、不自动刷机。新完整镜像的实机保留配置升级、重启和跨公网直连验收仍待完成；历史 `HARDWARE-EVIDENCE-21.json` 不代表 Release 22 的实机验收。直连效果仍取决于上游 NAT、防火墙和对端条件，不承诺吞吐提升。

## 安装

下载 `mt300n-v2-22-production-sysupgrade.bin` 并核验 SHA256。已有本项目固件可备份后在 LuCI“系统 → 备份/升级”选择保留配置升级；这一路径已做离线配置保留测试，尚未进行新镜像实机刷写验收。不要强制刷入其他型号。版本标识 `/etc/mango-release` 应为 `22`。
