# Release 26 — GL-MT300N-V2 · IKEv2 VIP 稳定 + SSR 回退不再卡轮换

基线：设备 `mango-release=26`（OpenWrt 25.12.5，`luci-app-mango-ikev2`）。  
本目录收录相对运行固件的热修复；**不是**完整 sysupgrade 镜像。用户凭据与 ZeroTier 网络 ID 不入库。

## 问题

### 1. 健康路径每 30 秒 flush VIP
`mango-ikev2-watch` 每 30 秒调用 `mango-ikev2-failover`。隧道已正常时仍执行 `clear_vip`（`ip -4 addr flush`）再 `pin_vip`。地址一删，内核清掉以该地址做 SNAT/masquerade 的 conntrack，长连接周期性中断。

### 2. SSR 回退默认截断节点轮换
热修复曾在 `bump_fallback_fail` 里：UCI 未配置时默认 `ssr_fallback=1`、`ssr_fallback_fails=6`，达到阈值后调用不存在的 `mango-ikev2-fallback-ssr` 仍 `exit 0`。后续「失败 2 次切节点」逻辑执行不到，会卡在当前节点（例如备用2）连续探测数百次。ROM 原版无此逻辑。

## 修复

文件：`hotfix-files/usr/libexec/mango-ikev2-failover`

- 健康路径与 `mark_up`：不再先 `clear_vip`；`pin_vip` 在 VIP 已正确时不动。
- 拨号前 / datapath 失败重拨前：仍保留 `clear_vip`。
- SSR 回退改为 **UCI 显式 opt-in**（未配置视为关闭）；未设置次数或 helper 不可执行时不中止。
- 仅当 helper 存在且执行成功时才 `exit`；失败或缺失则继续 IKEv2 节点轮换。

## 应用

```sh
cp -a /usr/libexec/mango-ikev2-failover /usr/libexec/mango-ikev2-failover.bak
# 覆盖 hotfix 文件后：
chmod 755 /usr/libexec/mango-ikev2-failover
# watch 每轮重新 exec 脚本，无需重启即可生效
```

## 验证（GL2 / 192.168.8.1）

- 脚本 `ash -n` 通过。
- VIP：连续两次 `pin_vip` 无 Deleted。
- SSR：当前无 `ssr_fallback` UCI、无 helper 时，`bump_fallback_fail` 返回且不退出，轮换逻辑可继续执行。
