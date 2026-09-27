# 第20版修订2测试构建

新增启动期Mango防火墙重复安装优化，继承R3核心补丁、守护保护、预检软限制和网站测试修复。
普通启动及fw4调用均在资源锁内核对期望规则、实际Mango表和策略路由；完全一致才复用，表缺失/变化/读失败仍安装。
未跳过首次DNS安装、未取消预检，实际启动提速尚待刷机验证。

本分支保留修订1构建记录，最新交付认准 **release20-r2** 工作流及产物，固件内标识 `20-test-r2`。
根目录旧的 mt300n-v2-round2.zip 属于第19版历史基线，不是本次输入。
本次输入为 release20-r2-source.zip.b64（Base64编码源码ZIP），工作流校验整个ZIP及每个文件后解包编译。
仅刷成功构建产物中的sysupgrade.bin；源码ZIP和Base64文件都不能刷机。

源码SHA256：`15680dc09ca7045ed20a2900bd235586ef20437dae09391203277ebdfe1a7a5a`

[修订2构建记录](https://github.com/liuyong2027/mt300n-v2-openwrt/actions/workflows/release20-r2.yml)
