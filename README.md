本次修订：默认简体中文，补充防火墙与软件包管理翻译；合并空节点列表修复、iOS 指纹支持、紧凑节点列表、手动单次 Ping 和当前策略连通性测试。节点详细参数在编辑窗口。新增功能仍需实机验证。

# GL-MT300N-V2：功能增强测试固件

第一轮已成功：基础镜像 13.50 MiB，距设备分区上限约 2240 KiB。
上一版镜像为 13.81 MiB。用户已确认修复后 WAN、LAN、全局代理和大陆分流可用。当前增强版需重新构建、测量容量并进行实机测试。

## 本轮功能

- 专用 Xray LuCI 页面：编辑多个 VLESS / RAW(TCP) / REALITY / Vision 节点，选择当前节点。
- 四模式：全部直连；大陆分流；全局代理；GFW 域名列表分流（命中代理，其余直连）。
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
提交源码 ZIP 时也会触发一次构建，没有定时任务。

流程执行 Python 数据裁剪测试、Lua 策略测试、JS/shell 语法检查、独立网络命名空间 nftables 语法/重复加载检查。
编译成功后，用 qemu-mipsel-static 运行实际 MIPS Xray 的 run -test，校验三种模式 JSON 和已打包的规则库。
这些检查不代替节点连通性、DNS、Wi-Fi、ZeroTier 网关及模式切换的实机测试。

下载 capacity-report-运行编号，查看体积、规则大小、manifest、源码版本和日志；全部检查通过后另提供 mt300n-v2-TEST-firmware-运行编号，包含 sysupgrade.bin、SHA256SUMS 和说明。测试固件保留 30 天。
报告保留 7 天。容量初筛要求距 16064 KiB 分区上限至少 1 MiB，这不是实测 overlay 空间。

## 固定来源和许可

- 官方 OpenWrt 25.12.5，commit f0a60eee2fe051741c643ea6118718aae1ef17fb，使用其固定 feeds。
- Xray 26.3.27 和 ZeroTier：上述官方 packages feed。
- 本轮不再使用通用 luci-app-xray，改用专用页面和服务，减小体积并避免两套配置抢占防火墙。
- GeoIP：v2fly/geoip，CC-BY-SA-4.0；GeoSite：v2fly/domain-list-community，MIT。版本与哈希见 scripts/cn_rules.py。
- 自写脚本和页面按 MIT 许可提供；上游组件保持各自许可。

公开仓库不提交节点凭据、订阅地址、UUID、ZeroTier 身份私钥。测试样例仅使用虚构凭据。

## 试用前

仅用于 GL-MT300N-V2。先备份当前配置，准备官方恢复固件并确认设备恢复步骤。不要将源码 ZIP 或报告 ZIP 当成固件。不要直接套用旧配置；从原厂固件迁移的刷写入口与镜像兼容性需要在操作前核对。首次通过有线连接测试，先检查普通上网，再配置节点和 ZeroTier。

## 本次新增与修复

- 已固化页面 modeOption 引用修复，以及启动配置使用 config.pending.json 的修复。
- Wi-Fi LED 改为 phy0tpt 无线活动触发器，避免 wlan0 与 phy0-ap0 接口名称不一致。
- 支持粘贴单条/多条 vless:// 分享链接、Base64 内容，以及 HTTPS 订阅下载。仅导入 TCP/RAW + REALITY + Vision；显示跳过数量，最多 64 条、48 KiB。相同服务器/端口/UUID/SNI 更新，不删除原有节点。导入后刷新页面，选择节点并保存应用。订阅地址只保存在本地 UCI，绝不能提交到 GitHub。
- 百度/Google HTTPS 测试可选择路由器直连或当前分流策略。显示 HTTP 结果、耗时与 curl 错误码。这验证服务路径，不等同于 LAN 透明代理端到端测试。
- 域名白名单在所有模式强制直连，包括子域名；没有黑名单。
- GFWList 是域名规则，不是 GFW IP 库。只转换域名规则与域名例外；路径、正则、通配符表达式不会扩大匹配，会统计跳过数量。
- China IP/GFW 域名手动更新：HTTPS 下载、格式/配置验证、空间检查、原子替换。China IP 另核对上游 SHA256。失败保留旧规则；结果显示在页面。更新保存到 /etc/mango-rules，占用可写空间；保留新文件之外至少 512 KiB 余量。CN GeoSite 仍使用固件内精简版本，不在路由器下载完整大型 GeoSite。
- Xray 进程由 procd 守护。可启用自动切换并选择备用节点：每 60 秒通过独立的本机 SOCKS 检测端口探测 Google/Cloudflare；任一成功就保留当前节点；连续三轮均失败才轮换，无备用节点则重启当前节点。默认关闭。切换状态在 RAM，不反复写闪存；应用配置回到主节点。外网整体故障也会导致探测失败，并不等于已经证明节点坏了。
- 本机测试端口 10808/10809 仅监听 127.0.0.1，不向 LAN/WAN 开放。

新功能需要固件内新增 curl 和 coreutils-base64，不能只替换旧版页面 JS。增强版容量、LED、订阅下载、更新、守护和实机 DNS 仍需验证。
