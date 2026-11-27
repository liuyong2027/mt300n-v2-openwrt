# Release 28 — GL-MT300N-V2 IKEv2

适用于 GL.iNet GL-MT300N-V2（ramips/mt76x8）。以 Release 27 的 IKEv2 构建配方为基础，使用相同的 OpenWrt 源码和 production 内核配置。

- 主服务器、备用服务器 1 和备用服务器 2 各有独立的远端 UDP 端口。留空使用标准 IKEv2 端口。
- 配置非 500 的远端端口时，客户端从本地 UDP 4500 的 NAT-T socket 发起协商，以保留指定的远端端口。
- 简化 LuCI 的本端 ID、远端 ID 提示，沿用通用 IKEv2 根证书说明。

镜像版本标识为 `/etc/mango-release=28`。Release 27.0.2 之后的根证书和 ChaCha20-Poly1305 修复随基线纳入本版。升级前请备份 IKEv2 配置、证书和 ZeroTier 身份。

主服务器 UDP 24450 的修正在当前实机上通过双向流量验证。本文对应的新镜像仍待刷机验收。
