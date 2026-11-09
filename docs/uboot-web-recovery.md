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

## 2026-11-09：重新检索型号专属资料

检索范围包括WE410443、Singtel-ST、WPS/recovery/failsafe/TFTP、原始OpenWrt提交
及后来的同型号变种实测。部分wiki/论坛直连被Anubis或抓取错误阻挡；可检索到
wiki正文，并直接读取官方commit邮件与作者发布的变种实测，未将读取失败算成已读。

### 已找到的直接证据

| 来源 | 明确记录 | 对本机的边界 |
|---|---|---|
| [OpenWrt首次支持提交](https://lists.infradead.org/pipermail/lede-commits/2025-June/025765.html)，`b6a07dd0914e`，2025-06-07发布 | 作者因bootloader密码锁采用外接SPI写入，并配置bootpartition后安装 | 支持这条已发表安装路线；不证明所有运营商变种的bootloader完全一样 |
| [OpenWrt WE410443设备页](https://openwrt.org/toh/arcadyan/astoria/we410443)，OEM installation/TFTP章节 | 记载SPI安装；TFTP boot入口有未知密码阻碍 | 未提供Singtel-ST按WPS开机进入Web recovery的实测步骤 |
| [Telus变种作者记录](https://gist.github.com/dthomas1202/37eb8179457eb73d31a5d57da935824e)，2026-06-05 | 作者报告Telus的bootloader未锁，可经串口访问并使用TFTP；其镜像还需处理不同TRX预期 | 是Telus证据，不能当Singtel-ST免密码或镜像通用的证明 |
| [Singtel WE410443-ST规格](https://cdn1.singteldigital.com/content/dam/singtel/business/sb/Support/connectivity/routers/singnet/Singtel_Mesh_Extender_WE410443-ST_v1.2.pdf)，§2.4 | 定义WPS配对与灯态 | 未给出bootloader recovery按键流程 |

### 检索结论与未解

本轮未找到可核验的Singtel-ST “WPS+上电→某IP的免密码recovery”步骤。
这是有范围的检索结果，不是对功能不存在的证明；旧Claude泛用fork方案不能升级成
型号专属操作说明。现在也没有依据建议继续猜测不同的按住时长或破坏镜像来触发模式。

如果继续核实入口，可先读取本机UART启动日志，与上述发布记录核对。
设备页给出的串口规格是3.3V、57600、8N1；串口日志读取不等于绕过菜单密码。
SPI则是文献已记录的安装/备份路径，实际实施前仍须核对本机芯片、分区和备份。
本次网络检索没有进行任何设备写入或恢复出厂。
