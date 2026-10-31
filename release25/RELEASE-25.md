# Release 25 — GL-MT300N-V2 IKEv2 客户端（分流）

在 Release 24 基础上增加 **IKEv2 客户端** 构建配置，支持国内 IP 分流。

## 为什么单独一套镜像

MT300N-V2 仅 16 MiB 闪存。Release 24 生产镜像约 14.25 MiB，分区余量约 1.44 MiB（门禁要求 ≥1 MiB）。modular strongSwan 客户端安装体积约数兆字节，**无法与现有 Xray 同装**。因此：

| 构建配置 | 出口 | 国内分流 |
|----------|------|----------|
| `standard`（默认） | Xray（VLESS/VMess/SS） | 已有 `split` / `gfw` |
| `ikev2` | strongSwan IKEv2 | `split` / `gfw` / `global` / `direct` |

两套配置互斥，不要试图在同一固件里同时启用。

## IKEv2 镜像能力

- LuCI：`服务 → IKEv2 分流`
- 认证：EAP-MSCHAPv2 或 PSK。备用服务器可单独填写另一套用户名密码或预共享密钥；备用认证留空时沿用主服务器的账号或密钥。
- 重连：约每 30 秒检查一次。当前服务器连续两次拨号失败后改连另一台；备用同样失败两次后再切回主服务器。未填备用时继续重试主服务器。对端无声断开由 30 秒 DPD 发现。
- 流量：XFRM 接口 `xfrm-mango` + fwmark `0x101` 策略路由
- `split`：中国 IPv4 CIDR 直连，其余进隧道。上游 DNS 固定为隧道内的 `1.1.1.1` / `8.8.8.8`，局域网 53 端口重定向到本机 dnsmasq，避免国内 DNS 污染。
- `gfw`：仅 GFW 列表中的域名走隧道 DNS，解析得到的 IPv4 由 dnsmasq nftset 写入 `gfw4` 后进隧道；其余域名用 `223.5.5.5` / `119.29.29.29` 并直连。列表来自 gfwlist，`/usr/libexec/mango-ikev2-gfw-update` 写入 `/etc/mango-ikev2/gfw-domains.txt`。
- 这是按 DNS 结果分流，不是 Xray 的连接内域名嗅探。客户端若直接访问 IP、或域名不在列表中，不会进隧道。IPv6 不进隧道。
- 中国 IP 列表：`/usr/libexec/mango-ikev2-cn-update`
- 该镜像用 `dnsmasq-full` 替换默认 `dnsmasq`，以使用 nftset。

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
