# Release 26 — GL-MT300N-V2 IKEv2 客户端

在 Release 25 的 IKEv2 镜像上把 `/etc/mango-release` 定为 **26**，并修正 charon 被启动两次的问题。

## 相对 Release 25.1.0

- 开机只保留 `swanctl` 启动的 charon。旧的 `ipsec` starter 在首次开机和每次应用 IKEv2 时都会被关掉，避免 `charon already running` 之后 vici 拒绝连接、根证书停在磁盘上。
- 其余行为与 25.1.0 相同：虚拟地址钉在 `xfrm-mango`、保存并应用后重载服务、防火墙放行局域网到隧道的转发、根证书支持 PEM 和 DER。

## 构建

推送到触发分支且改动落在 `release26/**` 或 `.github/workflows/release26.yml` 时，GitHub Actions 编译 IKEv2 sysupgrade.bin。镜像内 `mango-release=26`。

本地：

```bash
python3 release26/prepare.py
cd source26
MANGO_BUILD_PROFILE=ikev2 MANGO_KERNEL_PROFILE=production bash scripts/prepare.sh
```

## 刷机

可用 Release 25 的配置保留升级。刷入后 `/etc/mango-release` 应为 `26`。
