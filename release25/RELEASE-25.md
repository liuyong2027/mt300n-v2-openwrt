# Release 25 — GL-MT300N-V2 · IKEv2 热修复汇总

基线：设备上已刷入的 `mango-release=25` / `mango-build-profile=ikev2`（OpenWrt 25.12.5，`luci-app-mango-ikev2`）。  
本目录收录相对 ROM 的实机热修复文件与默认值补丁，**不是**完整重新编译的 sysupgrade 镜像。用户凭据、节点 IP、ZeroTier 网络 ID 不入库。

## 主要修改

### IKEv2 / strongSwan
- 多服务器故障切换：主用 → 备用1 → 备用2（`server` / `server2` / `server3` + 对应 `remote_id*`）。
- NordVPN 适配：本端 ID 留空；ESP 优先兼容 `sha1`（避免 `AUTH_TRUNC`）。
- 多 LAN 捕获：`lan_device` 支持空格分隔多接口（如 `br-lan ztc3q2tbgr`），ZeroTier 侧流量可一并进分流。
- 事件日志：`mango-ikev2-log` + LuCI「连接日志」页（最近切换记录）。
- 状态/探测：`mango-ikev2-status`、`mango-ikev2-probe`（含 Google/百度探测按钮所需后端）。

### 分流与 DNS
- 大陆分流（`split`）：国内 IP（`cn4`）直连，其余 IPv4 进隧道；DNS 默认国内，GFW 域名走隧道 DNS。
- GFW 模式：`gfw4` nftset + 域名列表。
- 列表更新：LuCI 一键更新国内 IP / GFW 域名；`lists-status` 显示条数与时间；下载走 WAN 直连。
- IPv4 防泄漏：`fail_closed`；公网 IPv6 不进隧道并在 LAN 转发侧丢弃；`filter_aaaa=1` 减少 AAAA。

### LuCI
- 文案：主/备用1/备用2、模式说明、LAN 多接口说明、列表更新区。
- ACL/菜单：日志页、状态与列表相关 exec 权限。

### ZeroTier / 防火墙（默认值补丁）
- 补回 `mangozt` 区域、`lan→mangozt`、`mangozt→wan`（IKEv2 profile 相对旧 Xray 包漏迁）。
- WAN 入站 `Allow-ZeroTier-Direct`：UDP `9993` ACCEPT（本机侧直连放行；上级 NAT/UPnP 仍取决于外层路由）。

### 其它实机项（配置层，不作为通用包默认）
- Wi-Fi LED：`phy0-ap0`（板级差异，按需）。
- NordVPN 根证书安装路径：`/etc/swanctl/x509ca/`（证书文件本身不入库）。

## 热修复文件清单

见 `hotfix-files/`（路径相对根文件系统）：

| 路径 | 相对 ROM |
|------|----------|
| `usr/lib/mango-ikev2/model.lua` | 已改 |
| `www/luci-static/resources/view/mango-ikev2.js` | 已改 |
| `www/luci-static/resources/view/mango-ikev2/log.js` | 新增 |
| `usr/share/luci/menu.d/luci-app-mango-ikev2.json` | 已改 |
| `usr/share/rpcd/acl.d/luci-app-mango-ikev2.json` | 已改 |
| `usr/libexec/mango-ikev2-{cn-update,failover,generate,gfw-update}` | 已改 |
| `usr/libexec/mango-ikev2-{lists-status,log,probe,status}` | 新增 |
| `etc/init.d/mango_ikev2` | 已改 |
| `etc/uci-defaults/95-mango-ikev2` | 建议替换为含 ZT 防火墙默认值的版本（见同目录补丁） |

未改相对 ROM：`mango-ikev2-fw`、`mango-ikev2-watch`。

## 验证范围（实机 GL1 / 192.168.10.1）

已验证：
- IKEv2 建立、`xfrm-mango`、split 模式国内直连 / 海外走隧道。
- 多接口捕获（`br-lan` + ZeroTier）。
- 列表更新与 LuCI 日志/状态。
- `mangozt` 与 WAN UDP 9993 规则写入 nft。

未覆盖 / 限制：
- 未重新全量编译并刷写完整 Release 25 镜像。
- 上级路由不做端口转发时，外网 IPv4 ZeroTier Direct 仍可能受限；本机 IPv6 路径可用。
- IPv6 不进入 IKEv2 隧道（设计如此）。

## 应用方式

1. 备份当前配置与 `/etc/mango-ikev2`、swanctl 证书。
2. 将 `hotfix-files/` 按路径覆盖到路由器（保留可执行位）。
3. 应用更新后的 `95-mango-ikev2` 中防火墙段落，或手动执行等价 `uci`（见 `uci-defaults-95-mango-ikev2.patch.sh`）。
4. `/etc/init.d/rpcd reload`；`/etc/init.d/mango_ikev2 restart`；必要时 `/etc/init.d/firewall reload`。

后续正式镜像应将本目录文件合入 `luci-app-mango-ikev2` 包源后再走完整构建与刷机验收。
