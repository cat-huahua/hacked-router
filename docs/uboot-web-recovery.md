# WE410443 原厂 U-Boot recovery：尚未验证的入口

2026-10-31 更正。公开 MediaTek U-Boot fork 有 HTTP recovery 实现；
**这不证明 Singtel WE410443-ST 原厂 bootloader 包含或启用了同一实现。**
旧版把“同SDK”和fork的“enhanced”描述推成原厂必有，还给出猜测IP、按键和上传命令，
这些步骤没有本机bootloader或真实请求证据，现撤回。

## 已解

- 本仓库已解码官方extender rootfs；正常系统更新经 `autofw`、`arcupload`、
  `arc_uploadhelper`，有CRC与footer封装验证。见[实际调用链](singtel-extender-autofw.md)。
- 管理界面的登录锁、SSH认证和bootloader认证是不同路径；恢复管理密码不能由
  “ping通了”或“出现一个HTTP页面”来证明。
- OpenWrt有WE410443目标与官方sysupgrade/initramfs镜像；首次安装与后续sysupgrade
  是不同操作。见[准备与持久化工具](singtel-openwrt-recovery.md)。
- 公开fork代码只能作为寻找HTTP parser/恢复模式的线索，不能替代原厂二进制或观察。

## 未解

- 原厂是否支持HTTP/TFTP recovery，触发条件和按键时长是什么。
- 恢复模式的IP、端口、上传字段、目标分区以及镜像接受规则。
- 是否验签、是否允许RAM-only启动，以及是否有读取配置的接口。

长按按键可能恢复出厂设置，不能将猜测按键流程称为“零损失”。
普通管理页、HTTP200、网络重新连通都不等价于已进入bootloader recovery。
设备离线时也无法通过该接口写flash；等待工具应等待已确认的服务出现，
而不是把断网当作自动刷写触发器。

## 本地观察工具

`openwrt/recovery.py watch --url <observed-url>` 只对一个用户指定的URL执行有期限的GET，
可将页面存到仓库外以供检查。它不枚举地址、不提交固件、不修改DNS、不尝试密码。
返回的`recovery_verified`始终为false：内容需与本机恢复协议独立核对。
它不是可用刷机入口的证明。

## 证据索引

| 材料 | 支持范围 |
|---|---|
| 本地`docs/singtel-extender-autofw.md`的VA/file offset表 | 原厂系统更新调用链，不能推断bootloader实现 |
| 本地`docs/singtel-extender-password-change.md` | 页面真实流程、脚本混淆与未解认证状态 |
| [官方OpenWrt设备页](https://openwrt.org/toh/arcadyan/astoria/we410443) | 支持型号及安装资料；仍需确认本机硬件/入口 |
| [OpenWrt目标定义](https://github.com/openwrt/openwrt/blob/v25.12.6/target/linux/ramips/image/mt7621.mk) | `Device/arcadyan_we410443`，不是原厂recovery实现 |
| [ec-/u-boot-mt7621](https://github.com/ec-/u-boot-mt7621) | 旧版引用的独立fork；本仓库未证明其与本机bootloader字节匹配 |

本篇没有真机恢复测试、写flash结果或已验证的bootloader替换方案。
