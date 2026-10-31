# WE410443 OpenWrt：镜像准备、等待观察与配置持久化

2026-10-31。对象是Singtel **WE410443-ST extender（MT7621）**，不是ARM/Broadcom
WG9116AEAC23-ST主路由。软件准备不等于首次安装入口已经打通；本轮没有连接或刷写设备。

## 已解：当前仓库工具的能力边界

本次基于原有134个tracked文件作全仓审阅，包括52篇docs、恢复/等待/登录脚本、
13份设备页面、云端模拟器和离线解码工具。原文件hash与阅读清单保存在仓库外。

- `singtel_mesh/recover.py` 与 `recover.sh` 登录原厂系统并恢复信道/名字，还可同步上游
  设备备注；不是OpenWrt刷机器，也不是断电自动恢复服务。
- `setch.py` 与 `recover.py` 的示例5GHz频道，与`apply_config.py`/`final_apply.py`
  中不同；不能把某个脚本默认值当成用户当前需要的配置。
- 这些原厂写入脚本读取返回值或回读RAM配置，没有证明冷断电后flash保留。
- 旧改密脚本未复现页面真实生成表单流程；反复试密码还会混入持久登录锁。
- `autofw_server.py` 是正常系统更新协议服务；HTTPS和镜像footer验证仍有独立约束。
- 旧`uboot-web-recovery.md`引用的是独立fork；原厂恢复IP、按键和上传协议仍未验证。

## 已解：官方OpenWrt镜像

已从OpenWrt官方25.12.6目录下载并按固定SHA-256与长度核对两个镜像。
公开工具不捆绑固件，不包含凭据或节点名称。

```sh
python3 openwrt/recovery.py prepare /private/openwrt-we410443
```

| 用途 | 文件尾缀 | 字节数 | SHA-256 |
|---|---|---:|---|
| RAM-only测试启动材料 | `initramfs-kernel.bin` | 7923587 | `98d8e06e6d5ecbc4924ec7aee3267de7876482d04ee7c7b4546c51ed5c9a36ba` |
| 持久安装/已装OpenWrt的升级材料 | `squashfs-sysupgrade.bin` | 9241136 | `7efd576e3bb792b849077e29454bd8455f90e8313d656853dc68e8f81917cddb` |

完整文件名前缀均为 `openwrt-25.12.6-ramips-mt7621-arcadyan_we410443-`。
固定hash来自官方profiles与下载目录，工具还限制长度并拒绝覆盖不匹配的既有文件。
这验证下载文件身份，不是对目标机型兼容性的实机验证或发行者签名的独立验证。

**initramfs通常运行在RAM中；仅成功启动它不建立可持久保存设置的flash overlay。**
官方目标定义包含sysupgrade与initramfs两种image，没有为该目标列出独立factory上传镜像。
不能把sysupgrade文件交给原厂升级页或猜测的recovery表单，并宣称必然接受。
官方设备资料记载SPI直接写入的安装方式；它也不证明用户机器存在免拆机的恢复入口。

## 已解：有期限地等待一个已知HTTP服务

```sh
python3 openwrt/recovery.py watch \
  --url http://<observed-device-address>/ \
  --timeout 300 --save-page /private/recovery-page.html
```

只对明确指定的URL发GET；没有地址扫描、密码尝试、POST或flash命令。
超时会失败。保存页面可能包含设备标识，应留在仓库外。
HTTP200只说明某服务返回页面，结果始终标记`recovery_verified=false`和`flashed=false`。
它不会因ping失败、断电或普通登录页出现而触发刷写。
真正刷写需要设备有稳定供电，且已确认恢复协议和接受的镜像；离线本身不是刷写入口。

## 已解：OpenWrt安装后的持久化检查代码

`openwrt/mesh-settings`是给**已经安装OpenWrt并有本地管理权限**的WE410443使用的shell工具。
它不是原厂密码恢复器，不解除原厂登录锁。
可通过已有控制台或SSH把脚本安装到`/usr/sbin/mesh-settings`，再执行：

```sh
mesh-settings check
# 在LuCI或uci中设置好所需配置后：
mesh-settings commit
mesh-settings mark
# 完成一次受控断电/重新上电，并重新连接后：
mesh-settings verify
```

- 核对`/tmp/sysinfo/board_name=arcadyan,we410443`。
- 必须存在squashfs `/rom` 和以jffs2/ubifs/ext4/f2fs可写挂载的`/overlay`。
  拒绝tmpfs overlay和不满足条件的RAM启动环境。
- `commit`调用`uci commit`和`sync`，不在每次启动时重写flash。
- `mark`仅把UCI配置文件hash保存在overlay；`verify`对比hash，不输出密码/SSID等内容。
- 检查失败表示配置改变、baseline缺失或存储条件不满足，不单独证明坏flash或固件bug。
  检查通过也不能保证任意写入时刻断电都不丢数据。

`MESH_SETTINGS_ROOT`仅供主机上用合成目录测试读取/校验；此模式禁止真实UCI commit。

## 未解

1. 原厂系统当前为何掉电丢配置：漏提交、mesh重新同步、启动恢复或flash故障均未排除。
2. 本机原厂bootloader是否提供免密码恢复入口，其地址、触发条件、表单与签名要求。
3. 首次OpenWrt安装的实际可用路径；当前不知道管理密码，不能靠等待脚本创造权限。
4. 实际设备上的flash布局、RAM启动、WiFi与冷断电配置保留验证。

## 证据索引

| 材料/位置 | 支持内容 |
|---|---|
| `singtel_mesh/recover.py:39` / `recover.sh` | 原厂登录后恢复频道/名称，无固件写入 |
| `singtel_mesh/setch.py`、`apply_config.py`、`final_apply.py` | 示例信道选择不同，不能盲目复用 |
| `docs/singtel-extender-password-change.md`证据表 | 真实页面与旧改密脚本的差异 |
| `docs/singtel-config-engine.md`、`singtel-boot-event-bus.md` | RAM配置、commit及软件重启消息路径 |
| `docs/singtel-extender-autofw.md`证据表 | 原厂下载、CRC、footer与flash路径，非bootloader证明 |
| [官方设备页](https://openwrt.org/toh/arcadyan/astoria/we410443) | WE410443支持与安装资料 |
| [官方profiles.json](https://downloads.openwrt.org/releases/25.12.6/targets/ramips/mt7621/profiles.json) | 型号`arcadyan_we410443`、supported_devices、文件大小/hash |
| [官方下载目录](https://downloads.openwrt.org/releases/25.12.6/targets/ramips/mt7621/) | 两类官方镜像及SHA-256 |
| [官方目标源码](https://github.com/openwrt/openwrt/blob/v25.12.6/target/linux/ramips/image/mt7621.mk) | `Device/arcadyan_we410443`、sysupgrade recipe与KERNEL_INITRAMFS |
| [OpenWrt flash layout](https://openwrt.org/docs/techref/flash.layout) | `/rom`、`/overlay`、`rootfs_data`的持久存储关系 |
| `tests/test_openwrt_recovery.py` | loopback GET、固定hash/损坏拒绝、RAM overlay拒绝与hash变化测试；非实机刷写 |
