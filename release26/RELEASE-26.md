# Release 26 — GL-MT300N-V2 · IKEv2 VIP 稳定固定

基线：设备 `mango-release=26`（OpenWrt 25.12.5，`luci-app-mango-ikev2`）。  
本目录收录相对运行固件的热修复；**不是**完整 sysupgrade 镜像。用户凭据与 ZeroTier 网络 ID 不入库。

## 问题

`mango-ikev2-watch` 每 30 秒调用 `mango-ikev2-failover`。隧道已正常时，健康路径仍执行：

1. `clear_vip` → `ip -4 addr flush dev xfrm-mango`
2. `pin_vip` → 再把 VIP `/32` 加回

隧道地址被删掉时，内核会清掉以该地址做 SNAT/masquerade 的 conntrack，长连接（经 VPN 的 NAT 流）会周期性中断。

## 修复

文件：`hotfix-files/usr/libexec/mango-ikev2-failover`

- 健康路径与 `mark_up`：**不再**先 `clear_vip`。
- `pin_vip`：VIP 已正确时直接返回；仅删除不匹配的地址，缺失时再 `replace`。
- 拨号前（`prepare_dial`）与 datapath 失败重拨前：仍保留 `clear_vip`，避免 charon 从残留 10.x 源地址发包。

## 应用

```sh
cp -a /usr/libexec/mango-ikev2-failover /usr/libexec/mango-ikev2-failover.bak
# 覆盖 hotfix 文件后：
chmod 755 /usr/libexec/mango-ikev2-failover
# watch 每轮重新 exec 脚本，无需重启即可生效
```

## 验证（GL2 / 192.168.8.1）

- 脚本 `ash -n` 通过。
- 对测试 VIP 连续两次 `pin_vip`：`ip monitor address` 第二次无 Deleted。
- `clear_vip` 仅保留在拨号准备与 datapath 失败重拨路径。

未覆盖：完整隧道恢复后的长连接 soak（当前节点拨号仍可能失败，属独立连通性问题）。
