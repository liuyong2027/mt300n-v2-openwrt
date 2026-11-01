# Release 25 — GL-MT300N-V2 IKEv2 客户端（分流）

在 Release 24 基础上提供 **IKEv2 专用镜像**（与 Xray 互斥），并合入实机验证过的热修复与默认值补强。

## 为什么单独一套镜像

MT300N-V2 仅 16 MiB 闪存。Release 24 生产镜像约 14.25 MiB，分区余量约 1.44 MiB。modular strongSwan 客户端约数兆字节，**无法与现有 Xray 同装**。因此：

| 构建配置 | 出口 | 国内分流 |
|----------|------|----------|
| `standard`（默认） | Xray（VLESS/VMess/SS） | 已有 `split` / `gfw` |
| `ikev2` | strongSwan IKEv2 | `split` / `gfw` / `global` / `direct` |

## 本版相对首个 IKEv2 镜像的修复与优化

### IKEv2 / strongSwan
- 主服务器 + 备用1 + 备用2 轮换；备用可单独认证账号。
- NordVPN：本端 ID 留空；ESP 使用 `aes128-sha1` / `aes256-sha1`（避免 `AUTH_TRUNC`）。
- `lan_device` 支持多接口（如 `br-lan ztc3q2tbgr`），LAN 与 ZeroTier 流量一并捕获。
- 连接事件日志、状态查询、连通探测（含日志页）。

### 分流与 DNS
- `split`：国内 IPv4（`cn4`）直连，其余进隧道；DNS 默认国内，GFW 域名走隧道 DNS。
- `gfw`：`gfw4` nftset + 域名列表。
- LuCI 一键更新国内 IP / GFW 列表，并显示条数与时间；列表下载走 WAN 直连。
- IPv4 防泄漏；公网 IPv6 不进隧道（LAN 侧丢弃），`filter_aaaa` 减少 AAAA。

### LuCI
- 主/备用命名与说明、多 LAN、列表更新区。
- **根证书**：显示安装路径与加载状态；支持上传或粘贴 PEM 安装到  
  `/etc/swanctl/x509ca/nordvpn-root-ca.pem`（并同步 `ipsec.d/cacerts`）。
- 连接日志页。

### ZeroTier / 防火墙默认值
- 补回 `mangozt` 区域、`lan→mangozt`、`mangozt→wan`（IKEv2 profile 相对旧 Xray 包漏迁）。
- WAN 入站 `Allow-ZeroTier-Direct`：UDP `9993` ACCEPT。  
  （上级 NAT/UPnP 仍取决于外层路由；本机 IPv6 可用于 ZT 直连。）

### 其它
- Wi-Fi LED 默认绑定 `phy0-ap0`（`96-mango-wifi-led`）。
- 升级保留：`/etc/mango-ikev2/`、UCI、swanctl/ipsec CA 目录。

## 构建

推送到触发分支且改动落在 `release25/**` 或 `.github/workflows/release25.yml` 时，GitHub Actions 编译 IKEv2 sysupgrade.bin。产物在运行的 artifact `25-ikev2-image-<run>`（保留 14 天）。

本地：

```bash
python3 release25/prepare.py
cd source25
MANGO_BUILD_PROFILE=ikev2 MANGO_KERNEL_PROFILE=production bash scripts/prepare.sh
python3 scripts/kernel-profile.py configure --tree openwrt --profile "$MANGO_KERNEL_PROFILE"
make -C openwrt defconfig
```

## 验收范围

- 仓库含 swanctl/nft 生成与 shell/JS 语法回归；镜像门禁要求剩余空间 ≥1 MiB、SquashFS 1 MiB 块、根文件系统无 `xray`、`mango-release=25`。
- 实机已验证：IKEv2 建立、split、多接口捕获、列表更新、LuCI 证书/日志、`mangozt` 与 UDP 9993、LED。
- 特定 NordVPN 节点偶发 `INTERNAL_ADDRESS_FAILURE`（拿不到 VIP）属运营商侧，不视为本镜像配置错误；备用节点轮换可缓解。
- 上级路由器不做端口映射时，外网 IPv4 ZeroTier Direct 仍可能受限。
