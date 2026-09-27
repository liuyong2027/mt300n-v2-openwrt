# R3 USB 测试构建准备

2026-09-27：仅准备源码，尚未运行云端构建、生成新固件或部署补丁。

本地四项构建选择测试通过：默认配置不改核心、USB 两版配置一致、feed 版本不符拒绝、
recipe 变化或存在未审查补丁时拒绝。完整 OpenWrt 构建和 shell 工作流尚未执行。

## 实机阻碍

SanDisk Cruzer Glide 3.0 已被 USB 控制器识别，接口类型为大容量存储，但固件没有
USB storage／SCSI 磁盘驱动，也没有 FAT／exFAT 文件系统驱动，因此没有 `/dev/sd*`。
没有格式化 U 盘，也没有识别其现有文件系统。

实机内核包 ABI 为 `6.12.94~7454efdd8d9a10b38faa716db2837fa2-r1`；
官方目标仓库公布的内核为 `6.12.94~2fe195f1cc4f533c70c3c6ea555ac460-r1`。
不能强行混装。不向仅剩约 1.3 MiB 的 overlay 写入约 32.8 MiB 的核心，
也不使用 `/tmp` 存核心进行性能对比，以免新增 RAM 占用改变结果。

## 三种构建选项

| profile | USB 支持 | Xray 核心 |
|---|---|---|
| `standard`（默认） | 保持原有选择 | 原版 |
| `r3-usb-baseline` | USB storage、FAT、exFAT、block-mount | 原版 |
| `r3-usb-patched` | 与 baseline 相同 | Vision UDP 443 拒绝前移，标识 OpenWrt-Mango-R3EarlyReject |

USB profiles 不增加 swap/extroot 或自动格式化，不承诺支持 NTFS／ext4。
先只读确认 U 盘文件系统；若不是 FAT/exFAT，需另行增加匹配驱动，不应直接格式化。
依赖由 OpenWrt Kconfig 选择；prepare 在 defconfig 后检查所有指定驱动是否仍选中。

手动 workflow_dispatch 的 `profile` 选择对应构建；push 触发仍为 standard。
同一干净源码也可使用 `MANGO_BUILD_PROFILE=r3-usb-baseline bash scripts/prepare.sh`，
或使用 `r3-usb-patched`。每种 profile 使用独立干净构建目录。
本文件不构成启动云端编译或刷机的操作记录。

R3 模式锁定 packages feed 提交及 Xray Makefile 摘要，发现其他补丁拒绝继续。
补丁模式将 package release 提升为 2，并更改核心版本标识；默认模式不启用补丁。
OpenWrt 构建阶段负责应用补丁，失败必须停止；主机拨号边界回归记录见
[核心测试记录](patches/xray-core/TEST-RESULTS.md)。

每份成功测试产物含单个核心的固件、该次 rootfs 的独立 `xray`、SHA256SUMS、
profile 标记和容量报告。不会在 16 MiB 闪存同时放两个核心。
USB profiles 同样必须通过原有“距镜像分区上限至少 1 MiB”的容量初筛，
驱动装入后的实际可写空间、RAM 和启动情况仍需实机检查，不能降低门槛强行发布。

## 后续验证顺序

1. 获得编译授权后，先构建 USB baseline，再构建同源码的 USB patched；检查容量和 MIPS 配置验证。
2. 备份配置、保留原固件并准备本地恢复路径后，刷入 USB baseline。验证节点、国内直连、USB 挂载；不把新 ABI 的模块单独装到旧固件。
3. 只向 U 盘新建的测试目录写核心和日志，不覆盖原文件。保留 `/rom/usr/bin/xray` 与恢复步骤。
4. 测试前准备可自动回退的切换脚本，再临时切换核心；此脚本尚未实现，因此目前不提供手动替换系统核心命令。
5. 固定有线客户端、节点、模式、测速服务器；临时暂停自动切换并记录原状态，结束后恢复。没有额外 UDP 443 防火墙限制。
6. 原版与补丁版都从同一 U 盘运行，以免 squashfs 与 USB 读取性能差异成为混杂因素；环境变量、配置与采样方式保持相同。
7. 确认流量实际触发普通 Vision 的代理 UDP 443；测空闲、测速、测速后两分钟的 CPU/RSS/可用内存、PID 与 Google 响应，至少两轮对比。
8. 补测 TCP、DNS/其他 UDP、国内直连及允许 UDP 443 的例外。只证明拨号边界的主机测试不代替这些实机测试。

ZeroTier 可用于管理、采集；吞吐测试仍用客户端到本路由器的本地网线，避免叠加隧道路径。
切换核心前确认 SSH 回退可达；结束后恢复原核心、守护设置并明确通知用户可断开。
