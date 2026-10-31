# Release 25 — GL-MT300N-V2 IKEv2 客户端（分流）

在 Release 24 基础上增加 **IKEv2 客户端** 构建配置，支持国内 IP 分流。

## 为什么单独一套镜像

MT300N-V2 仅 16 MiB 闪存。Release 24 生产镜像约 14.25 MiB，分区余量约 1.44 MiB（门禁要求 ≥1 MiB）。modular strongSwan 客户端安装体积约数兆字节，**无法与现有 Xray 同装**。因此：

| 构建配置 | 出口 | 国内分流 |
|----------|------|----------|
| `standard`（默认） | Xray（VLESS/VMess/SS） | 已有 `split` / `gfw` |
| `ikev2` | strongSwan IKEv2 | `split` / `global` / `direct` |

两套配置互斥，不要试图在同一固件里同时启用。

## IKEv2 镜像能力

- LuCI：`服务 → IKEv2 分流`
- 认证：EAP-MSCHAPv2 或 PSK
- 流量：XFRM 接口 `xfrm-mango` + fwmark `0x101` 策略路由
- `split`：中国 IPv4 CIDR 直连，其余进隧道；列表由 `/usr/libexec/mango-ikev2-cn-update` 写入 `/etc/mango-ikev2/cn-cidrs.txt`
- 不支持 Xray 的 GFW 域名分流（无域名引擎）

## 构建

```bash
python3 release25/prepare.py
cd source25
MANGO_BUILD_PROFILE=ikev2 bash scripts/prepare.sh
# 随后按既有流程 make
```

默认 `MANGO_BUILD_PROFILE=standard` 仍产出 Xray 版，行为与 Release 24 一致。

## 验收范围

- 本仓库含 swanctl/nft 生成与 shell/JS 语法回归。
- 完整 `ikev2` 镜像需 CI 编译并通过 ≥1 MiB 分区余量门禁后再发布。
- 实机连通性、吞吐、与特定 VPN 运营商兼容性不在本提交保证范围内。
