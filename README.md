# GL-MT300N-V2 第二轮：精简分流固件测试

第一轮已成功：基础镜像 13.50 MiB，距设备分区上限约 2240 KiB。
第二轮已实现下列配置，待云端构建与静态运行检查，尚未实机验证，不是已验证的刷机成品。

## 本轮功能

- 专用 Xray LuCI 页面：编辑多个 VLESS / RAW(TCP) / REALITY / Vision 节点，选择当前节点。
- 三模式：全部直连；大陆分流（CN 域名/IP 直连，其他 TCP/UDP 代理）；全局代理。
- 仅保留 CN GeoSite 与 CN/private GeoIP，固定下载版本并验证 SHA256。
- ZeroTier 保留单独网络配置页，可选择允许哪些 ZeroTier IPv4 地址/网段借本机上网。
- 内部地址、实际 ZeroTier 接口路由直连。LAN 可访问 ZeroTier；不默认允许远端访问 LAN 或路由器管理后台。
- 代理范围限 LAN 与获准的 ZeroTier 客户端。路由器自身（包括 ZeroTier 隧道、节点拨号）直连。
- 代理模式拦截客户端普通 IPv4 DNS；大陆域名通过国内 DNS，其他域名通过代理 DNS。
- 代理模式下不转发这些客户端的公网 IPv6，也不转发不能代理的非 TCP/UDP 公网流量（例如公网 ping）。
- 代理模式下核心退出不会撤销转发阻断规则，避免自动转为直连。故障时大陆访问也可能中断；切到“全部直连”恢复普通转发。

## 使用顺序（待实机验证）

1. 默认“全部直连”，ZeroTier 关闭，固件不带个人节点或网络 ID。
2. 服务 → Xray 分流，添加节点并保存，再选择节点和代理模式并保存应用。
3. 服务 → ZeroTier，填写自己的 Network ID、启用，并到 ZeroTier Central 授权。
4. 如需 ZeroTier 客户端借本机上网，在 Xray 分流页启用网关并填写允许的客户端 IPv4 / CIDR。
5. 在 ZeroTier Central 添加经本机 ZeroTier IP 的默认路由，客户端允许默认路由，并将 DNS 指向本机 ZeroTier IP。

本机 ZeroTier 的 allow_default 应保持关闭，避免出口回指自己。仅加入网络不会自动改变客户端默认路由。
网关模式只允许白名单客户端到 WAN；不会开放 WAN 上的代理端口、远端 LuCI 或远端 SSH。
此测试固件管理 dnsmasq 上游（直连时 223.5.5.5 / 119.29.29.29，代理时本地 Xray DNS）并关闭流量卸载。
DoH/DoT 作为普通连接处理；未宣称可强制解密第三方加密 DNS。
GOMEMLIMIT 是 Go 的软限制，不是进程内存硬上限；仍需验证 128MB RAM 稳定性。

## 云端检查

仓库保留可审查的源码 ZIP，工作流先解压再构建。修改源码需重新打包上传。
Actions → MT300N-V2 capacity probe → Run workflow。
提交 ZIP 或工作流时也会触发一次构建，没有定时任务。

流程执行 Python 数据裁剪测试、Lua 策略测试、JS/shell 语法检查、独立网络命名空间 nftables 语法/重复加载检查。
编译成功后，用 qemu-mipsel-static 运行实际 MIPS Xray 的 run -test，校验三种模式 JSON 和已打包的规则库。
这些检查不代替节点连通性、DNS、Wi-Fi、ZeroTier 网关及模式切换的实机测试。

下载 capacity-report-运行编号，查看体积、规则大小、manifest、源码版本和日志；本阶段仍不上传刷机镜像。
报告保留 7 天。容量初筛要求距 16064 KiB 分区上限至少 1 MiB，这不是实测 overlay 空间。

## 固定来源和许可

- 官方 OpenWrt 25.12.5，commit f0a60eee2fe051741c643ea6118718aae1ef17fb，使用其固定 feeds。
- Xray 26.3.27 和 ZeroTier：上述官方 packages feed。
- 本轮不再使用通用 luci-app-xray，改用专用页面和服务，减小体积并避免两套配置抢占防火墙。
- GeoIP：v2fly/geoip，CC-BY-SA-4.0；GeoSite：v2fly/domain-list-community，MIT。版本与哈希见 scripts/cn_rules.py。
- 自写脚本和页面按 MIT 许可提供；上游组件保持各自许可。

公开仓库不提交节点凭据、订阅地址、UUID、ZeroTier 身份私钥。测试样例仅使用虚构凭据。
