# USB 文件共享

LuCI“服务 → 网络共享 → USB 文件共享”标签页提供分区选择、共享名称、局域网访客读写或只读，以及启用、卸载、取消授权。原 Samba 页面保留在“共享设置”标签页；旧 USB 页面地址仍可跳转。
新盘不会自动共享。首次点击启用后按 UUID 记住授权，同一分区再次插入会恢复；多个分区使用不同共享名称。
不自动格式化、修复文件系统或递归修改文件所有者/权限。只处理 sysfs 中确认属于 USB 的 FAT32、exFAT、ext4、NTFS 分区；重复 UUID、加密盘和已挂载到其他位置的盘拒绝启用。

可写共享为每个分区创建 `.samba-metadata`，缺失时在确认正确挂载后补回。拒绝符号链接元数据目录/数据库。Samba 的每共享挂载检查同时验证 UUID、USB 来源、挂载路径、文件系统、访问模式和授权；磁盘缺失时拒绝回落访问路由器内部目录。只读分区不建立可写元数据数据库。
为访问 ext4 原有文件，共享服务使用 root 文件身份，仍按所选只读/读写模式限制 SMB；未递归更改盘内文件权限。局域网访客获得整个获准分区的相应访问权，请仅授权愿意共享的分区。

原项目 USB 配置仅在旧检查脚本、`fstab.tr3600_usb` 和 `samba4.usb` 均匹配原方案时迁移：保留 USB 名称和 `/mnt/usb` 路径、备份配置到 `/root/.cudy-usb-backup`（目录700、文件600），转为 UUID 授权；未识别的其他挂载/共享保持原样。以后新盘路径为 `/mnt/cudy-usb/usb_<UUID>`。
Samba 必须只绑定 lan，模板保留 bind interfaces only=yes；本功能不开放 WAN、防火墙转发或公网端口。现有自定义普通共享继续由“网络共享”页面管理。

安全卸载先停止共享连接、同步写入，再进行普通 umount；不用强制或 lazy 卸载。失败明确报告并恢复配置。卸载后保留授权但本次插入不再自动挂载，重新插入后恢复。取消授权同样先卸载，成功后不再记住此盘。拔出整块磁盘前须卸载它的所有分区。

测试包含纯 Lua 生命周期/错误回退、真实 ARM64 UCI/nixio 私有备份与元数据目录重建、锁定 Samba init 生成/testparm 校验、LuCI 操作/刷新与 ACL 校验、最终固件精确内容核验。
RC1 实机已验证新 NTFS 盘授权只读、安全卸载、重新插入恢复和取消授权，以及换回原 FAT32 盘后自动恢复和 SMB3.1.1 读写/中文名/改名/删除/ADS。当前 iPhone“文件”客户端、可写 NTFS 和忙碌卸载实际客户端表现未全部覆盖。1.0.0 新镜像安装后仍须确认，详见 RELEASE-NOTES.txt。

挂载机制参考 [OpenWrt](https://openwrt.org/docs/techref/block_mount)，元数据机制参考 [Samba xattr_tdb](https://www.samba.org/samba/docs/current/man-html/vfs_xattr_tdb.8.html)。
