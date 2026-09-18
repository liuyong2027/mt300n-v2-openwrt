# GL-MT300N-V2 云端编译预检

当前阶段：验证软件包能否编译、基础固件能否放入内置闪存。**不是已完成的可刷固件。**

目标为标准 OpenWrt、Xray VLESS/RAW(TCP)/REALITY/Vision、ZeroTier，以及两者的网页配置。
最终需要直连 / 大陆分流 / 全局代理三模式，支持指定 ZeroTier 设备经本机代理上网。
这些分流、DNS、IPv6 和 ZeroTier 网关策略尚未实现或验证，不能因为预检通过就视为完成。

## 如何运行

打开仓库 Actions → MT300N-V2 capacity probe → Run workflow → 保持默认参数 → Run workflow。
首次默认不加入大陆规则库，先测系统、核心和管理页面的容量下限。
`include_rules` 可以加入完整上游 GeoIP/Geosite 作对比，但这不是最终精简规则方案。
流程没有定时任务，也不会自动刷路由器。

运行结束后查看 Summary，并下载 `capacity-report-运行编号`：包含容量报告、配置、固定源码版本及日志。
为避免误刷，本阶段不上传 bin 镜像。没有镜像、缺必要包、空间不足均报错，失败后仍尝试上传诊断。
如果构建日志显示容量超限，这是有用的预检结果；如果下载或编译失败，应先修复，不能据此判断放不下。

## 固定来源

- OpenWrt 25.12.5：`f0a60eee2fe051741c643ea6118718aae1ef17fb`，使用发布版自带固定 feeds。
- Xray：官方 packages feed 中的 26.3.27；本轮未做源码裁剪。
- Xray LuCI：yichya/luci-app-xray `521c5854d4433ce097e957c6b52f28423b0dc503`（3.7.1）。
- ZeroTier：同一官方 packages feed。轻量配置页在本仓库，匹配官方 UCI 配置，不混用其他发行版的防火墙字段。

网页与核心版本已按源码检查，但仍需运行验证。不要任意单独升级网页插件或混用软件源。
OpenWrt 25.12 使用 APK，不能照搬旧版 opkg 安装指令。

## 容量判断

从设备源码读取 IMAGE_SIZE（16064 KiB），保留官方 check-size，不扩大分区、不跳过校验。
报告额外用 1 MiB 余量做保守初筛；这不是实机 overlay 可用空间保证。
不带规则库的成功结果只能说明基础组合有机会，仍需加入规则、模式切换和必要依赖后再次构建。
也需验证 128MB RAM 下双服务同时运行的稳定性。

## 默认配置

不包含节点、订阅地址、UUID、REALITY 参数或 ZeroTier 网络 ID。
透明代理关闭，ZeroTier 关闭且无示例公共网络。未改 Wi-Fi、WAN 或 LAN 的上游默认配置。
后续填写敏感配置应在路由器本地进行，不提交到公开仓库。
旧版 clean.bin 不是源码基础，也不是已验证的恢复镜像。

## 自定义文件许可

本仓库新写的脚本与 ZeroTier 轻量页面按 MIT 许可提供，见 LICENSE。
OpenWrt、Xray、ZeroTier 和第三方 LuCI 插件保持各自上游许可。
