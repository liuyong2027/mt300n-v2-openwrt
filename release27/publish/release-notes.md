# Release 27 — GL-MT300N-V2 IKEv2

[下载固件 mt300n-v2-r27-recovery-2ba098d-sysupgrade.bin](https://github.com/liuyong2027/mt300n-v2-openwrt/releases/download/v27.0.0/mt300n-v2-r27-recovery-2ba098d-sysupgrade.bin)

将本次完成构建并已刷入设备的固件统一发布为 Release 27（标签 `v27.0.0`），替代旧 v27.0.1 发布页。直接发布 Actions 第 10 次构建的原始镜像，未重新编译或修改文件。已经刷入 SHA256 相同固件的设备无需重复升级。

## 主要修改

- 探测容错：先恢复分流和 DNS 路由；两个 ICMP 目标均失败时，再通过 xfrm-mango 探测两个 HTTPS 端点，保留 TLS 校验并绕过代理。连续 3 轮探测全部失败才开始 CHILD 修复，任一成功即清零探测失败计数。
- 受控恢复：优先保留 IKE 与 VIP，仅修复 CHILD；单节点连续 3 次 CHILD 修复失败后允许完整 IKE 重建，同一节点最多每 300 秒尝试一次。
- 终止确认：按旧 IKE SA 的唯一 ID 终止并轮询确认，必要时对同一旧 ID 升级一次 force；查询失败、旧 SA 未消失或清理期间出现新 SA 时，不清 VIP、不发起新拨号。
- 重协商等待上限：CONNECTING 等待 60 秒，重协商/删除等过渡状态等待 120 秒。中间状态变化不重置计时，恢复前重新查询 SA，优先保留已恢复的 INSTALLED CHILD。
- 退避调整为 **30、30、30、60、60、60、120、120、120、240、240、240、300、300……秒**；每个节点仍连续失败两次后轮换到下一个配置节点。服务启动、重启或保存应用时清零相关计数和等待状态，避免继承 300 秒档。
- 保留既有 WAN IPv4 绑定、关闭 MOBIKE、健康 VIP 原地保留、孤儿 IKE/VIP 解析、xfrm-link 初始化、空日志拒绝与 LuCI 日志权限修复；包含 `67f556a` 及 Issue #9 中适用于本机型和 profile 的修复。

退避从记录失败时起算，实际切换还包含协商、探测、清理和 watchdog 周期。`swanctl --timeout 15` 仅限制命令行等待，不是后台握手的硬上限。

## 版本和验证

- OpenWrt **25.12.5**，production 内核；`/etc/mango-release=27`。独立 IKEv2 profile 包含 ZeroTier，不含 SSR Plus+/Xray。
- 基线：`588ed68c02d8bbdaa0db19af106b91d9ec15c508`；本次源码：`2ba098ddff1b044c5bb0d7b23975c8a9135a42fc`。
- [完整构建及检查](https://github.com/liuyong2027/mt300n-v2-openwrt/actions/runs/42957607849)成功；51 项运行回归、3 项 WAN 检查及模型/语法检查通过。镜像格式、分区余量及 10 个打包修复文件哈希检查通过，下载后摘要再次核对一致。
- 用户刷机后回传的三个运行脚本哈希与本构建完全一致，IKEv2 主节点状态为 up、已建立 323 秒，当前事件日志包含成功记录。该结果属于初步刷机与连通验证；故障恢复、退避轮换、重启恢复及长期稳定性仍待实机验收。详见 `HARDWARE-ACCEPTANCE-27.json`。
- `firmware-format.json` 保留构建时的原始 pending 字段，后续用户回报单独记录，不改写原始构建证据。Issue #9 尚不据此关闭。

## 升级和校验

仅适用于 GL.iNet **GL-MT300N-V2**，不适用于本仓库的 Cudy TR3600。已有匹配的本项目 IKEv2 固件可保留配置升级；先备份配置及证书，通过有线 LAN 在 LuCI 上传 sysupgrade.bin，升级后核对节点、证书和连接状态。

- 固件大小：**9,896,230 字节（9.44 MiB）**。
- 分区余量：**6,553,306 字节（6.25 MiB）**。
- SHA256：`87088be86581dee5a9427fe226a00d12b3d5909f98c1723232883cc4b6ce6f6e`。

附件包含固件、SHA256SUMS、构建报告、源码差异说明和初步设备验收摘要。GitHub Source code 为本标签的构建配方，按 `release27/prepare.py` 可重建准备源码。
