# Release 27 — GL-MT300N-V2 IKEv2 稳定性修复

以 `588ed68c02d8bbdaa0db19af106b91d9ec15c508` 的 Release 26 构建配方为基线，保持原有 OpenWrt 与 feeds 固定提交及 production 内核配置。镜像内 `/etc/mango-release=27`。

## 修复范围

- 纳入 `a1aebc2` / `67f556a`：健康路径不 flush 正确 VIP；SSR 回退仅显式启用、阈值有效且 helper 可执行并成功时才结束轮换。
- Issue #9：从 netifd 的 WAN 运行状态取得真实 IPv4，生成 `local_addrs`，关闭 MOBIKE；拨号前清理隧道 VIP 并重新加载 WAN 绑定。WAN 暂未就绪时不使用 VIP 或任意网卡地址拨号。
- 只从当前节点的 SA 块提取 CHILD_SA/VIP；恢复 table 101、mark 规则和隧道 DNS 路由后再探测 ESP 通路。正确 VIP 原地保留，不打断 NAT 长连接。
- 修复 LuCI 日志读取权限：补充 `/tmp/log/mango-ikev2-events.log` 的精确只读授权，兼容 rpcd realpath 检查。
- 状态页必须有最近 90 秒内的隧道探测成功记录，SA 存在但 ESP 不通时不再报已连接。
- 拨号失败采用 30/30/60/60/120/120/240/240/300/300… 秒封顶退避，每两次失败轮换一个节点；不在同一轮连续拨多个节点。探活恢复后清零退避。flock 防止重叠拨号。
- 初始化等待 vici，失败时交由 watchdog 重试；不再因开机 WAN/vici 尚未就绪而丢失恢复任务。
- 服务启动、重启或保存应用时，同时清零节点失败次数、累计失败次数及等待截止时间，避免继承上一轮 300 秒档；即使 WAN/vici 暂未就绪，后续重试也从 30 秒开始。正常自动轮换仍按既定序列累计。

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
4. 模拟 ESP 断路，确认清理 VIP 后重拨；连续失败按退避轮换，不出现连接风暴。
5. 冷启动、WAN 续租/重连、ZeroTier 访问与 LuCI 保存应用后均能恢复。无现场设备验收前保留 Issue #9 打开。
