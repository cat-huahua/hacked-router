# WE410443-ST：Linux 启动、网络更新与 boot environment 的边界

本篇静态检查已验证解出的 WE410443-ST v6.02.00 build14 rootfs，重点是：设备进入所谓 recovery 后，能否由电脑提供 DHCP/DNS，再由原厂客户端下载固件。没有执行目标程序、连接设备或写 flash。本篇调用链证据主要来自 r2/readelf 与静态脚本；后续直接 Ghidra headless 的导出范围另见 [反编译覆盖](singtel-extender-decompile-coverage.md)。REA CLI 的旧 MIPS ABI admission 未通过，不能将直接 Ghidra 结果称为 REA Evidence。

## 已解：三类更新路径不能混同

| 路径 | 已确认入口 | 网络与接受条件 | 与当前 recovery 的关系 |
|---|---|---|---|
| Linux `autofw` | `usr/share/msg/sys_boot:48` → `arca.dbus.autofw:CMD_BOOT` | `ARC_SYS_AUTOFW_Url`，JSON POST `/GetFirmwareVersion`；curl 验证 peer，使用 `/usr/cert/`；下载后仍校验容器和 signature | 已有静态实现证据，尚未证明当前 recovery 会执行它 |
| Linux `arc_owl_fwupgrade` | `main` 根据参数选择分支，包括 `autofw_single` | 另一组 `ARC_SYS_AUTOFW_URL` / `ConnType`，wget-ssl 下载；HTTPS 使用 `/etc/autofw_ca` | 已确认存在另一套更新器；不是据名称便可判定的 bootloader recovery |
| 当前设备的 recovery 网络客户端 | 未确定 | 域名、协议、固件文件名、是否 TLS/TFTP、启动来源均待实际流量或该阶段代码对应 | 未解 |

`Url` 与 `URL` 是不同配置键，不能把大写键的其他品牌模板地址当作 Singtel JSON API 的地址。正常 Linux `autofw` 的公开出厂服务域名是 `firmware.singnet.com.sg`；配置生成与 TLS/JSON/签名证据见 [autofw 专篇](singtel-extender-autofw.md)。DNS 改写本身只改变解析结果，不满足这些已证实的 TLS 和固件校验条件。

## 已解：DHCP hook 更新地址，没有 DHCP 失败后转救援下载的分支

完整阅读 `usr/scripts/dhcpc.sh` 与 `dhcpc_bridge.sh`：

- WAN hook 的 `update_value` 配置 interface 地址、default route，并写入 DHCP 提供的 DNS/domain/lease 等配置（第 34 行）。`BOUND` 后按 WAN protocol 触发 `wan_done` 或相应 WAN 动作（58–87 行）。
- bridge hook 更新 LAN 地址、route、DNS/domain/lease（第 33 行）；`BOUND` 后调用 `lan0_update`（65–72 行），创建 `/tmp/data_ready`（75 行），并向 OWL 报告状态。
- 两个 `SWITCHNOIP` 分支都明确输出 `SWITCHNOIP not implemented`（WAN 147–148 行，bridge 123–124 行）。其计算备用地址后的实际设置语句被注释。
- 在这两个完整 hook 内，没有 HTTP/TFTP 固件请求或 DHCP 失败启动 recovery downloader 的命令。这只限定这两个 hook 的覆盖范围；不代表 DHCP daemon、agent 或 bootloader 不可能有另一套处理。

消息文件继续接入普通 Linux 服务：`lan0_update:4` 重启 NTP，`:5` 刷新 DNS resolver；`wan_done:8` 重启 dnsmasq，`:11` 重启 NTP。这些文件没有直接启动 recovery downloader。

因此，给收到 DHCP 的设备分配地址与 DNS 是可测试的联网准备；不能单凭它发送 DHCP，就认定已定位到某个固件下载协议。必须把后续 DNS/HTTP/TLS/TFTP 请求与具体客户端对应。

## 已解：autofw 有时间门槛，但不是检查 NTP 成功标志

`autofw` 导出 `is_got_ntptime`，VA `0x401d6c` / file `0x1d6c`，实际只有五条指令：

```c
// 参数来自 localtime() 结果的副本；+0x14 为 tm_year。
return tm->tm_year != 0x46; // 年份不是 1970
```

调度函数 VA `0x403790` / file `0x3790` 首先调用 `time`、`localtime`，复制 `0x2c` 字节的 `struct tm`，再调用此判断（`0x403818`）。失败分支 `0x403928` 写原字符串 `Didn't get NTP time, check 1min later`（字符串 VA `0x406004` / file `0x6004`），随后以 60 秒设置 timer（`0x403974–0x40398c`）。

静态事实是“1970 年时延后调度”，不是“必须收到了某台 NTP server 的响应”。NTP 是本固件正常校时来源；如果联网环境没有校时、设备又从 1970 启动，即使 DNS 和固件服务已准备好，正常 autofw 也可能持续延后。实际年月和服务运行状态尚未观测。

`sys_boot:25` 先调度 `ntpclient CMD_BOOT`，`:48` 调度 autofw。`sbin/arc_ntpclient:4–6` 通过 `arc_ntpdaemon start` 启动。ELF `arc_ntpdaemon` 的 `start_ntp`（VA `0x400cd8` / file `0xcd8`）读取 `ARC_SYS_NTP_Enable`，读取五个 `ARC_SYS_NTP_SERVER_%d`，执行 ntpclient。`_eval` 参数为 `ntpclient -h <servers> -i 20 -l -s`（`0x401068–0x4010b0`），子进程成功后写状态。

它确实在第一次成功时设置 `ARC_NTP_SYNCED=1`（`0x4011b4–0x401208`），并调用 `mng_action("fw_polling", "")`（`0x401218–0x401224`；字符串 VA `0x401778` / file `0x1778`）。但样本 `usr/share/msg/fw_polling` 只有注释 `#arca.dbus.crond:CMD_RESTART`，没有有效动作。因此不能把这个事件写成已证实会触发固件下载；上述 autofw 自己的年份判断才是已追到的时间门槛。

## 已解：OWL 的第二套下载器

`sbin/arc_owl_fwupgrade` 的 `main` VA `0x4017bc` / file `0x17bc` 接收命令行模式，`0x401868–0x401890` 比较 `autofw_single` 并进入 VA `0x402a40` 的分支。不要仅根据 usage 中的 `url` 把它解释成 recovery 服务地址。

另一个分支 VA `0x405528` 读取以下配置，直接由 `mapi_ccfg_get_str` 的调用和字符串地址对应：

| 配置键 | 字符串 VA / file offset | 读取点 VA |
|---|---|---|
| `ARC_SYS_AUTOFW_URL` | `0x41127c` / `0x1127c` | `0x4055c8–0x4055dc` |
| `ARC_SYS_AUTOFW_USERNAME` | `0x411290` / `0x11290` | `0x4055ec–0x4055fc` |
| `ARC_SYS_AUTOFW_PASSWORD` | `0x4112a8` / `0x112a8` | `0x40560c–0x40561c` |
| `ARC_SYS_AUTOFW_ConnType` | `0x412050` / `0x12050` | `0x40562c–0x40563c` |

这里只记录键名，不记录其值。HTTPS 分支在 `0x40575c–0x405770` 比较 `https`，在 `0x405778–0x4057a0` 格式化：

```text
wget-ssl -T 16 -t 1 --ca-directory=/etc/autofw_ca https://%s/%s -O /tmp/%s 2>&1
```

格式字符串 VA `0x4120f0` / file `0x120f0`。第二个路径参数与输出文件名使用 `version.txt`（VA `0x4120e4` / file `0x120e4`），`0x4057b4` 调用 `system`，`0x4057c0` 检查返回值。另一个分支使用同一 CA directory 下载配置给出的完整 HTTPS URL（字符串 VA `0x4113a0` / file `0x113a0`；`0x402d3c–0x402d94`）。也存在 FTP 分支，本轮未穷尽其 metadata parser、参数来源和固件验证链。

已证实该 downloader 有实际 HTTPS 命令和配置数据流；尚未把它接到 reset/recovery 按钮或特殊启动条件，也未完整验证 `wget-ssl` 自身的证书/hostname 检查实现。不能由 `--ca-directory` 单独推导完整 TLS 行为，更不能说 DNS 改写必然足够。

## 已解：Linux boot environment 工具不要求另输密码

`usr/sbin/uboot_env` 是 rootfs 中的 MIPS ELF，不是 bootloader 本体。其 `main`（VA `0x4009a0` / file `0x9a0`）解析 `--get`、`--set`、`--name`、`--value`，调用 `read_env` / `get_env` / `set_env` / `saveenv`。已检查的这些路径没有 password/login 校验调用。工具能否在真机使用，仍取决于已有 Linux 执行权限和 MTD 访问权限；这不是远程恢复或 bootloader 口令旁路。

`read_env` VA `0x400ef0` / file `0xef0` 打开固定 `/dev/mtd2`（字符串 VA `0x402ef0` / file `0x2ef0`），读 `0x1000` 字节。前四字节是 CRC，余下 `0xffc` 字节为 NUL 分隔的 `key=value`；CRC 的末尾取反与首字段比较发生于 `0x400fdc–0x400ff0`。`get_env` VA `0x401068` 与 `set_env` VA `0x40116c` 在该字符串区查找/更新。CRC 是完整性检查，不能把它称为环境认证或固件签名。

本轮没有实际 `/proc/mtd`，所以不能仅凭设备号把 `/dev/mtd2` 直接等同某个 OpenWrt DTS 的命名分区，也不能假设它包含当前设备完整 bootloader 配置。

### 静态可确认的本地错误处理缺陷

`saveenv`（VA `0x401358` / file `0x1358`）调用 `program_img_2(env, 0x1000, 0)`，然后在 `0x401384` 无条件返回 0。`program_img_2`（VA `0x401758` / file `0x1758`）通过 MEMGETINFO 取得 erase size，以 0xff 初始化 scratch buffer，复制 env，再 MEMUNLOCK / MEMERASE，最后写整个 erase block（`0x401850–0x40185c`）。打开、ioctl 或短写失败进入 perror 路径，但末尾仍返回 0（`0x4018bc`）。

这意味着“设置命令显示成功”不能证明 env 已持久保存，是本地 persistence 的错误处理问题。尚未动态复现；它要求已有 flash 写权限，不是已发现的 TFTP/bootloader 认证绕过，不能用它解释所有掉电设置丢失现象。

`arc_uploadhelper` 还先执行 `mngcli tmp_get current_bank`（VA `0x401bb4`，字符串 VA `0x40d178` / file `0xd178`），匹配 `BANK_A` / `BANK_B`。失败才进入读取 `uboot_env --get --name bootpartition` 的备用路径（argv 静态数据指针及 `0x401c40–0x401ccc`）。这属于运行中 Linux 的 A/B 选区，不能推出 recovery 在 LAN 上暴露了同样接口。签名和实际 flash 链另见 autofw 专篇。

## 未解与检索边界

- 没有从当前样本恢复出 bootloader 的 TFTP password 或其认证函数，也没有证实存在这种 password 机制。Linux BusyBox 的 `tftp` / `tftpd` applet 不构成 bootloader 的实现证据。
- 对已解 rootfs 普通文件做 recovery/rescue/TFTP 与公共域名检索，定位并跟踪了上述程序和脚本；未发现单独硬编码的 Singtel recovery 服务域名。该阴性结果不能排除 runtime 配置、flash env、字符串拼接、另一分区或 bootloader 中的域名。
- 不能由 normal Linux 的 autofw、OWL downloader 或 DHCP hooks 认定当前 recovery 使用其中哪一个。接下来有区分力的证据是实际 recovery 发出的 DNS question、HTTP path、TLS SNI、TFTP RRQ filename，以及流量是否在正常 Linux 服务启动前出现。
- 追加检查了持久保存的 raw kernel，结果见下节；没有 bootloader dump、UART log、实际 env dump 或目标执行证据。
- 没有生成或写入恢复固件，也没有由本轮代码证明 custom/OpenWrt image 可以通过原厂 signature 校验。

## 证据索引

以下相对路径均指同一已验证解出的 rootfs。代码与 rodata 位于 ELF 首个 LOAD 时，file offset = VA - `0x400000`；data LOAD 使用 readelf program header 单独换算。

| 样本 | SHA-256 | 本轮覆盖 |
|---|---|---|
| `usr/sbin/uboot_env` | `0e075af602bfb9b648268c354d60eb25393bccbbaee21226499631ab29a24553` | main、read_env/get_env/set_env/saveenv、program_img_2 反汇编 |
| `bin/busybox` | `4832a3cb81c5ffd7df7ef2326db5cd82b278ad7e7904ccca493d79e4c4465e19` | applet symlink/字符串；未反汇编 TFTP 协议实现 |
| `sbin/preinit` | `7d588552093153f6f043387bc32abbc87655700bc2e4e406331ea415e6496550` | ELF/启动字符串；未完整反汇编 |
| `sbin/sysup` | `54b89397592b48fc93d2d4400c1f45507b2eecf76e960a0de16d309007564384` | ELF/启动字符串；未完整反汇编 |
| `sbin/arc_rcS` | `ecb09fe0d0c47c82a7223da6e931eb401ee03607cb520682bdcebcecb2578cd1` | 完整脚本 |
| `sbin/arc_owl_fwupgrade` | `b97cf9fe005ae38263b1a80f9453071b86a91123bc6ec03e7ee9b95d9553a5a1` | CLI dispatch、配置读取、HTTPS command 的实际代码窗口 |
| `sbin/arc_ntpdaemon` | `b1ef3066fdd59e2479e67c7af4c3a41de4e063afc1730fe0229ff37b049ca82d` | 完整 start_ntp |
| `usr/sbin/autofw` | `8933428ea737eab326bae33b9bf69ecf5cdd12749fe1c0dc3235e82a38154027` | 本轮补读 is_got_ntptime 与 timer 调度；协议另篇 |
| `usr/scripts/dhcpc.sh` | `1311de210dfcd944ad87197d3a2d768db9ec4fdafca4957d85720222c54d1b5f` | 完整脚本 |
| `usr/scripts/dhcpc_bridge.sh` | `cd6a5bd04f210fcef9bc50b5c090ef2e0c497839eadcca0ee58bba78ff9a4e4b` | 完整脚本 |

文本证据：`usr/share/msg/sys_boot:25,48`、`lan0_update:4,5`、`wan_done:8,11`、`fw_polling:1`；`sbin/arc_ntpclient:4–6`。所有结论均为静态事实或明确标注的推断/未知，不包含目标运行实测。


## 追加：raw kernel 的 initramfs、网络启动与 A/B root 证据

持久样本 `WE410443-ST_v6.02.00_kernel.lzma-unpacked.bin` 为 7,743,232 字节，SHA-256 `9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a`，MIPS LE，映射 base `0x81001000`。本节只进行有边界的静态核对，未重新解 crypto 或重建 kallsyms。

### 已解：嵌入 kernel config 不启用 initrd 或内核 IP 自动配置

`IKCFG_ST` 位于 file `0x5334a0`，其后 8 字节起为 gzip config；结束标记 `IKCFG_ED` 位于 file `0x535c44`。解压 config 可直接核对：

```text
CONFIG_IKCONFIG=y
# CONFIG_IKCONFIG_PROC is not set
# CONFIG_BLK_DEV_INITRD is not set
# CONFIG_IP_PNP is not set
CONFIG_DEVTMPFS=y
CONFIG_DEVTMPFS_MOUNT=y
CONFIG_SQUASHFS=y
CONFIG_ARC_SQUASHFS_FS_CRYPTO=y
CONFIG_SQUASHFS_XZ=y
CONFIG_SQUASHFS_LZMA=y
# CONFIG_CMDLINE_BOOL is not set
```

全 raw 文件未见 ASCII cpio `070701` / `070702` / `070707`，只出现一个 gzip magic，对应上述 IKCONFIG；未找到可提取的内嵌 initramfs 恢复程序。结合 `CONFIG_BLK_DEV_INITRD` 未启用，当前样本没有支持“这个 kernel 自带独立 initrd recovery 用户空间”的证据。magic 检索不是通用嵌入镜像检测器，不能排除另一分区、另一 kernel 或 bootloader 自己带网络恢复。

`CONFIG_IP_PNP` 未启用，说明该 kernel 未编译 Linux 的 IP autoconfiguration 路径；不能把用户看到的 DHCP 直接归因于该内核的 IP_PNP，更不能由此排除 userspace DHCP。

file `0x67c7e0` / VA `0x8167d7e0` 的内置启动字符串是：

```text
console=ttyS1,57600n8 root=/dev/mtdblock5 init=/sbin/preinit rootfstype=squashfs,jffs2
```

这是本地 flash root 的证据。实际传入和最终生效的完整 cmdline 仍需启动日志或 `/proc/cmdline`，不能只由字符串断言。

### 已解：实际 root mounting 初始化代码读取 bootpartition 并切换 root5/root8

字符串 `bootpartition` 位于 file `0x5d9a48` / VA `0x815daa48`。真实代码 xref 在 file `0x733fec–0x734008` / VA `0x81734fec–0x81735008`：`lui/addiu` 构造该字符串地址，以 `a0=0`、`a1=bootpartition` 调用 VA `0x81003408`（file `0x2408`）的查值 routine。后续完整 kallsyms 核验将此地址对应为 kernel 的 `nvram_get`（类型 `T`）；这是本 kernel 的符号，不是 bootloader 的 getenv。

返回非空时，`0x81735050–0x81735078` 与字符串 `"1"`（VA `0x81641060` / file `0x640060`）逐字节比较；相等后在 root device buffer 中找 `mtdblock5`（字符串 VA `0x815daa88` / file `0x5d9a88`，调用 `0x81735088`）。若找到，则计算 buffer 末尾，在 `0x817350a8–0x817350ac` 把最后一个字符写为 `0x38`（ASCII `8`）。随后打印 `Boot from %s`（字符串 file `0x5d9a94`，调用 VA `0x817350b8`）。

这段实际代码证实了本地 root 分区 A/B 选择：相应条件下把 mtdblock5 改为 mtdblock8。代码窗口没有 DHCP/DNS/TFTP 或远程固件读取，不能将这种分区选择叫作“联网 recovery”。它也没有展示密码比较或认证旁路。

### 本节剩余边界

对该 raw kernel 大小写敏感字节检索未见 `tftp`、`firmware.singnet`、`bootcmd`、`bootargs`、`bootdelay`、小写 `recovery`；包含 Recovery 的 Wi-Fi/TCP 状态与错误处理字符串不构成固件恢复入口。唯一小写 `password` 命中来自无线 invalid PSK 的诊断文本（file `0x5f182c` 起），不是候选口令值或登录校验逻辑。

当前证据更支持“此 kernel 常规启动本地 rootfs，再由 Linux 服务联网”，未定位用户当前 recovery 的独立下载器。内核没有 initramfs/网络启动的相关证据，不等同已穷尽整个 kernel，也不排除恢复模式运行另一份程序。下一步仍需将 recovery 实际网络请求与客户端代码对应。

## 2026-11-12 后续证据

[按键路径](singtel-extender-button-path.md)确认Linux运行后的WPS是配对、Reset约10秒是清配置并重启。
[DHCP探测路径](singtel-extender-dhcp-detection.md)将已捕获Discover对应到内置探测函数，
并补出OFFER→event9→普通Ethernet uplink选择→DHCP client/server切换。
两者均没有建立bootloader recovery入口；缺少的该阶段代码不能由普通Linux流程替代。
