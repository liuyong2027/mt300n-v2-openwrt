# 第20版修订3测试构建

固件标识20-test-r3，继承r2启动优化和R3核心补丁。新增候选认证失败继续遍历、全失败退避、配置变化取消旧恢复及后台应用状态提示。
切换脚本通过实机边界测试；页面提示待真实LuCI验收。构建必须通过Linux回归、MIPS配置及容量检查后才能交付BIN。
本次输入为release20-r3-source.zip.b64，工作流校验ZIP及逐文件SHA256。旧版归档保留。源码不能刷机。

源码SHA256：`a4c570d8a0ca898d4037ab2e5e2bb4687f1506174bf94d09f04973a1deca0b4e`

[修订3构建记录](https://github.com/liuyong2027/mt300n-v2-openwrt/actions/workflows/release20-r3.yml)
