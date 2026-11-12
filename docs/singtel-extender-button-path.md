# WE410443-ST：WPS/Reset 与 recovery 的代码边界

核对日期：2026-11-12；原厂 v6.02.00 build14。继续沿已解 Linux 用户空间追踪按键，确认了配对和恢复出厂设置的实际路径，**没有发现可据此指定的 bootloader recovery 按键序列**。本轮没有操作设备按键、执行目标或修改配置。

## 已解：出厂映射与时间单位

`usr/share/config/etc/gpio/button_map.txt` 是运行时 `/etc/gpio/button_map.txt` 的出厂模板：

| 按键名称 | GPIO | 有效电平 | spec | 已读 Linux 行为 |
|---|---:|---|---:|---|
| `wps` | 3 | low | 0 | 松开后可进入 WPS 配对动作 |
| `default` | 18 | low | 10000 | 按下持续达到约10秒后触发恢复出厂设置 |

`reboot` 的示例定义被注释，不能当成该模板中启用的独立按键。上述为样本默认文件，不是从当前 flash 读回的运行时配置。

`arc_gpiod:main` 解析 `spec` 的十进制值，保存到动作记录。`process_polling` 用 monotonic 时间差计算 `seconds*1000 + nanoseconds/1000000`，再与 `spec` 比较，所以这里的10000是毫秒。轮询与调度会造成实际触发时刻偏差，不能将其当成精准硬件定时。

## 已解：Reset 是清配置，不是联网恢复

持续按住、达到 `default` 阈值的分支执行 `mng_action("ui_factory_defaults", "")`。相应消息脚本依次清日志、`restore_defaults`、重启日志、`commit`、`reboot`。松开分支也存在 default 动作处理，并以等待状态避免重复触发。

这条链是**恢复出厂设置并重启**。所读分支没有启动 DHCP/DNS/TFTP 下载、没有切入已验证的 recovery downloader，也没有证明进入备用系统。因此不能建议“长按 Reset”作为保持配置的恢复实验，它可能正好清掉用户设置。

## 已解：WPS 分支由网络状态选择配对方向

在正常而非工厂测试模式下，WPS 松开后经过一个120秒的动作间隔检查。GPIO3初始化的上次动作时间为-120，使首次动作不必等待开机120秒；不能把这个间隔误写成需要按住120秒。

只要某个无线频段 WPS 已启用，分支读取临时键 `ARC_LAN_0_DHCPC_IP_Flag`：

- 解析值为0：设置 uplink 状态，向 driver 设置 `WscUplink=1`，发出 `ui_wlan_apcli_uplink_pbc_both`；消息脚本调用 `CMD_APCLI_UPLINK_PBC_BOTH`。
- 非0：清 uplink 状态，设置 `WscUplink=0`，发出 `ui_wps_btnpbc`；消息脚本调用 `CMD_WPS_PUSHHWBUTTON`。

这些是**上游 AP 配对 / 下游无线客户端配对**，不是已证实的 recovery 入口。工厂测试分支另作私有证据保存，本页只记录其类别。

## 启动阶段与未解

`usr/share/msg/sys_boot` 启动 `gpiod CMD_BOOT`；本篇分析的是正常 Linux 已运行后的 daemon。`arc_rcS` 调用 `/etc/init.d/rcS S boot`；`preinit` 的已导出入口没有在所读文本中提供 WPS 进入联网恢复的分支。

这不能排除 bootloader 在 Linux 之前采样同一 GPIO。现有材料缺少该设备实际 bootloader 本体，不能把 daemon 的GPIO/时长规则直接套到“按住WPS上电”。此前 WPS 上电观察也只确认恢复了原厂管理页面，见 [现有观察](singtel-openwrt-recovery.md)。

要建立 recovery 入口，需要该阶段的 bootloader/启动日志，或者按键操作与 DHCP/DNS/HTTP/TFTP 请求的明确对应。即使看到普通 `autofw` 请求，也仍需分开验证 recovery、TLS 和 firmware 接受条件，见 [boot/access 边界](singtel-extender-boot-access.md)。本篇不能提供已验证的 recovery 按键操作。

## 证据索引

`arc_gpiod` SHA-256：`8ea2cd69525eaeb127bb2758a356eff5c303feca46bada80ad2bf42c87fa3295`。
该 ELF RX 段 file offset = VA − `0x400000`。以下地址来自保存的 Ghidra 导出；关键窗口另经 r2 反汇编，并逐指令 bytes 对照原文件。

| 证据 | 符号 / VA / 文件位置 |
|---|---|
| 映射模板 | `usr/share/config/etc/gpio/button_map.txt`：`wps=3`、`spec=0`，`default=18`、`spec=10000` |
| daemon 入口和 parser | `main@00400c50`；打开 `/etc/gpio/button_map.txt`，解析 `spec` 后存入动作记录 |
| GPIO3首次动作初始化 | `004013ec` 的 `li v0,-0x78`，对应上次动作时间-120 |
| 按键轮询 | `process_polling@00401bdc` |
| 毫秒换算与阈值 | `00401d54–00401da8`，1000、1000000、unsigned比较 |
| 达阈值后的出厂恢复 | `00401e54–00401e9c`，LED/日志及 `mng_action` |
| WPS动作间隔 | `004020c0–004020f4`，uptime差与 `0x78` 比较 |
| WPS方向选择 | `004021d0` 起的读取/比较及动作分支；`ARC_LAN_0_DHCPC_IP_Flag` |
| 出厂恢复消息 | `usr/share/msg/ui_factory_defaults`，restore/commit/reboot |
| 配对消息 | `usr/share/msg/ui_wps_btnpbc`、`ui_wlan_apcli_uplink_pbc_both` |
| daemon启动 | `usr/share/msg/sys_boot:4` |

私有 `recovery-trigger-20261112/buttons/evidence.json` 保存输入 hash、所核对指令窗口及 bytes匹配结果；同目录保存原始 pseudocode、反汇编窗口。没有执行这些动作，也没有把普通按钮 API 当作 bootloader 实现。
