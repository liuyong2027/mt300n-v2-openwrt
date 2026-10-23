# Release 24 — GL-MT300N-V2

以 Release 23 为基线，合入设备上验证过的内存保护与代理无响应恢复。保留原有功能、配置、ZeroTier direct UDP 和 ZeroTier UPnP discovery 规则。ZeroTier 运行文件与 Release 23 逐字节一致。

- 固定 `vm.min_free_kbytes=16384`（16 MiB）、`vm.watermark_boost_factor=0`、`vm.watermark_scale_factor=10`。
- Xray 使用 `GOGC=50`，保留 `GOMEMLIMIT=48MiB`。
- DNS 在未配置时补充 `max-tcp-connections=8`；已有自定义数值和其他选项保留。
- 仅当可用内存低于 16 MiB、自动故障切换已启用、核心已运行至少 180 秒，且本机 SOCKS 连续两次无响应时，才尝试停止旧核心后恢复。使用操作锁并检查配置和进程身份；900 秒冷却，每小时最多 3 次。无法确认旧核心退出时禁止启动新实例。

可从 Release 23 选择“保留配置”升级；请先备份。固件不包含用户代理节点、密钥或设备专属节点优先级。已有自定义 DNS 上限不被覆盖；内存配置文件通过 sysupgrade 保留，已有 `99-oom-guard.conf` 继续保留。此次不改变核心版本、内核构建配置、分流、Web 管理或 ZeroTier 维护触发方式。

发布必须通过原有回归、真实 nftables、实际 MIPS Xray 配置验证、MIPS BusyBox ash/nc 与 dnsmasq 检查、安装文件哈希、固件格式和至少 1 MiB 分区余量检查。具体结果、源码差异、设备热修复证据和校验和随附件提供。

设备证据来自 Release 23 加相同四个运行文件，重启及超过 10 小时复查通过，期间没有新 OOM。完整 Release 24 镜像尚未刷机验收；完整 LAN/IPv6 转发、吞吐、断电恢复与人为 OOM 不在本次设备验证范围内，不承诺代理速度提升。

这些参数不等于预留固定的应用可用内存，也不能保证消除 OOM。[Linux 6.12 VM 参数说明](https://www.kernel.org/doc/html/v6.12/admin-guide/sysctl/vm.html)、[Go GC 参数说明](https://go.dev/doc/gc-guide)、[dnsmasq 参数说明](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html)。
