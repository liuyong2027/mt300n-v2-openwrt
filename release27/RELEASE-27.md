# Release 27 — GL-MT300N-V2 IKEv2 稳定性修复

以 `588ed68c02d8bbdaa0db19af106b91d9ec15c508` 的 Release 26 构建配方为基线，保持原有 OpenWrt 与 feeds 固定提交及 production 内核配置。镜像内 `/etc/mango-release=27`。

## 修复范围

- `mango-ikev2-link`：与 `/lib/functions/network.sh` 共用时使用 `set -e`（不用 `-u`）。`network_flush_cache` 会 unset `__NETWORK_CACHE`，在 `set -u` 下会导致 xfrm-mango 创建失败、IKEv2 起不来（2026-11-10 GL2 保留配置刷机实机确认）。
- 纳入 `a1aebc2` / `67f556a`：健康路径不 flush 正确 VIP；SSR 回退仅显式启用、阈值有效且 helper 可执行并成功时才结束轮换。
- Issue #9：从 netifd 的 WAN 运行状态取得真实 IPv4，生成 `local_addrs`，关闭 MOBIKE；拨号前清理隧道 VIP 并重新加载 WAN 绑定。WAN 暂未就绪时不使用 VIP 或任意网卡地址拨号。
- 只从当前节点的 SA 块提取 CHILD_SA/VIP；恢复 table 101、mark 规则和隧道 DNS 路由后再探测 ESP 通路。正确 VIP 原地保留，不打断 NAT 长连接。
- **探测容错**：先恢复隧道路由，再探测两个 ICMP 目标；ICMP 均失败时补测两个固定 IP 的 HTTPS 端点，绑定 xfrm-mango、保留 TLS 证书校验并绕过代理。任一目标成功即可确认数据通路；连续 3 轮全部失败才开始 CHILD 修复，成功一轮清零探测失败计数。
- **重协商等待上限**：初始 `CONNECTING` 从发起拨号或首次观察起等待 60 秒，重协商/删除等过渡状态从首次观察起等待 120 秒。中间状态变化不重置计时；有 `INSTALLED` CHILD 时优先验证数据通路。超过上限后重新读取 SA，仍卡住才进入受控清理与退避，避免无限跳过。watchdog 按周期观察，因此这些是触发恢复的计时阈值，并非精确完成时限。
- **IKE 仍在、仅数据通道异常**：优先 `swanctl --initiate --child`，保留 VIP 与 IKE；仅配置一个节点时，连续 3 次 CHILD 修复失败后允许完整 IKE 重建，同一节点最多每 300 秒尝试一次，短暂探活成功不取消该冷却时间。
- **确认终止后再重拨**：全量拨号和保存应用使用旧 IKE SA 的唯一 ID 终止、轮询确认，必要时仅对同一旧 ID 升级一次 force。查询失败、旧 SA 未消失或清理期间出现新 SA 时，不 flush VIP、不发起新拨号；不触碰其他连接。无 VIP 的孤儿 IKE（如 NordVPN `INTERNAL_ADDRESS_FAILURE`）也走该确认流程，不误把 `[4500]` 当 VIP。
- `mango-ikev2-log`：无参或非法 result 直接退出，禁止写入空事件行。
- 修复 LuCI 日志读取权限：补充 `/tmp/log/mango-ikev2-events.log` 的精确只读授权，兼容 rpcd realpath 检查。
- 状态页必须有最近 90 秒内的隧道探测成功记录，SA 存在但 ESP 不通时不再报已连接。
- 拨号/修复失败采用 **30/30/30/60/60/60/120/120/120/240/240/240/300/300… 秒**封顶退避，每两次失败轮换一个节点；不在同一轮连续拨多个节点。等待从记录失败时起算，不包含前面的协商、探测或清理耗时；watchdog 周期还会影响实际下一次执行时间。探活恢复后清零退避。flock 防止重叠拨号。
- `swanctl --initiate --timeout 15` 仅限制命令行等待时间，不强制终止后台握手；后续由 CONNECTING 计时与确认清理处理，不能把 15 秒描述为握手硬上限。
- 初始化等待 vici，失败时交由 watchdog 重试；不再因开机 WAN/vici 尚未就绪而丢失恢复任务。
- 服务启动、重启或保存应用时，同时清零节点/累计失败次数、等待截止时间、探测/修复计数和过渡/恢复冷却状态，避免继承上一轮 300 秒档；即使 WAN/vici 暂未就绪，后续重试也从 30 秒开始。正常自动轮换仍按既定序列累计。

这是原有的独立 IKEv2 profile，包含 ZeroTier，不含 SSR Plus+ 或 Xray。Issue #7（SSR 手机端探测按钮）及 Issue #9 的 TR3600 safexcel/SSR 开机恢复不适用；不引入不存在的 SSR 回退默认值或 helper。

## 构建与交付

```sh
python3 release27/prepare.py
cd source27
sh tests/test_ikev2_model.sh
MANGO_BUILD_PROFILE=ikev2 MANGO_KERNEL_PROFILE=production bash scripts/prepare.sh
```

GitHub Actions 的 Release 27 工作流在 `codex/mt300n-v2-release27` 推送时验证并编译，上传 sysupgrade 镜像、SHA256、构建日志和最终 rootfs 修复哈希。镜像必须保留至少 1 MiB 分区余量；禁止把编译成功等同于实机验收。

## 刷机后待验收

先在本地备份配置，通过有线 LAN 在原管理地址升级；本任务不自动刷机。保留配置升级需检查 `/etc/mango-release` 为 `27`，并确认 swanctl 的 `local_addrs` 等于 WAN IPv4。

1. IKE endpoint 使用 WAN 地址，隧道 VIP 只用于隧道流量；国内直连、国外 DNS/HTTPS 正常。
2. 长连接跨过多个 30 秒健康周期不中断，`ip monitor address` 无周期性删除 VIP。
3. SA 存在时清空 table 101，下一轮应先补路由再探测，不触发无意义重拨。
4. 阻断 ICMP 但允许隧道 HTTPS 时不触发修复；连续 3 轮隧道探测全失败后先修 CHILD，保留 VIP；单节点连续修复失败后才尝试受冷却限制的完整 IKE 重建。
5. 观察 CONNECTING 与重协商超时，确认正常短暂过渡不打断、长期卡住能恢复；清理未确认时不能提前 flush 或重拨。失败按每档 3 次退避、每节点 2 次失败轮换。
6. 冷启动、WAN 续租/重连、ZeroTier 访问与 LuCI 保存应用后均能恢复。无现场设备验收前保留 Issue #9 打开；这些恢复策略不等同于已经解决远端不响应握手的问题。
