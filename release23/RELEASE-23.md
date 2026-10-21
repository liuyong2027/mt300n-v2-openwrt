# Release 23 — GL-MT300N-V2 · ZeroTier UPnP 修复

以正式版 Release 22（v22.0.0）为基础，仅适用于 GL.iNet GL-MT300N-V2。

修复辅助程序依赖固件中不存在的 `timeout` 命令，导致无法读取 WAN 网关、未生成 `ZeroTier UPnP discovery` 规则的问题。改用已有 ubus 的 `-t 3` 超时参数，不增加软件包依赖。

保留 `ZeroTier direct UDP` 三个明确配置的 UDP 端口，以及仅允许当前 IPv4 WAN 网关、UDP 源端口 1900 到本机高位端口的 UPnP 回复规则。继续在启动、防火墙重载、WAN 变化及 ZeroTier 启停时维护。现有功能、默认启用状态、代理、无线、防火墙、ZeroTier 身份、网络和 local.conf 配置沿用 Release 22。

2026-10-21 已在用户刷好的 Release 22 设备上应用同一行修复，确认三个端口与实际监听一致、当前网关的 UPnP 规则生成。重复刷新两次及重载防火墙后，两条规则和唯一 WAN 跳转均恢复；配置文件哈希、ZeroTier 与代理进程 PID 保持不变。原辅助程序已备份。记录见 `DEVICE-HOTFIX-EVIDENCE-23.json`。

构建要求通过原有 Linux 回归、13 项真实 nftables UDP 用例、实际 MIPS Xray、BusyBox、Lua、内核、镜像格式、源文件哈希和至少 1 MiB 分区余量检查；新增在无外部 timeout 的受限 PATH 中执行真实辅助程序的测试，以及编译目标 ubus 原生超时参数检查。

以上实机结果仅覆盖 Release 22 上的相同辅助程序热修复。Release 23 完整镜像的保留配置刷写、重启和跨公网直连验收仍待完成，本次构建不自动刷机。直连效果取决于上游 NAT、防火墙和对端条件。

从 Release 21 或 22 升级：先备份配置、核验 `SHA256SUMS`，在 LuCI“系统 → 备份/升级”上传 `mt300n-v2-23-production-sysupgrade.bin` 并选择保留配置。不要使用强制刷写。新镜像版本标识 `/etc/mango-release` 为 `23`。已在当前路由器上应用热修复后，两条规则已可使用；重新刷入完整镜像仍属于另一项设备升级操作。
