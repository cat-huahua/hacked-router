# WE410443-ST：原厂 MCU 内存读取接口

2026-11-12，静态核对 v6.02.00 build14 原厂 kernel。找到可从本地 wireless ioctl 调用的 N9 memory-dump 请求链；尚未从设备取得返回数据，也未证明 ROM 区域可读。此接口需要运行中的原厂 driver、本地执行权限与 kernel log 读取能力，不是 bootloader/recovery 或免登录通道。

## 已确认：show dumpmem 请求 N9 的64 bytes

`ap_privtab` 将 `show` 注册为 ioctl `0x8bf1`；`rt28xx_ap_ioctl` 将其送到 `RTMP_AP_IoctlHandle` 的 case `0x11`，再进入 `RTMPAPPrivIoctlShow`。show表里的 `dumpmem` 指向 `show_mem_proc`。

语法为 `show` 参数 `dumpmem=<十六进制地址>`。handler用 `simple_strtol(...,16)` 解析地址，不接受长度参数；每次请求固定64 bytes。存在完整 shell 且已识别正确 Wi-Fi interface 后，下面仅作为**待验证的单块诊断模板**：

```sh
iwpriv "$IFACE" show 'dumpmem=00080000'
```

这里 `0x80000` 来自原厂 ROM patch 的 MCU download address，选择它是为了用已有64-byte patch内容做对照。**尚未验证该 command的地址语义与 download address相同**，所以此模板不代表已经建立可用 ROM dump流程。不要把host虚拟地址或PCI BAR偏移直接代入。

`MtCmdMemDump` 构造68-byte payload：首4 bytes为原始查询地址，余64 bytes清零；地址在已读host链中没有映射。响应 callback `CmdMemDumpRsp` 从 response `+4`复制64 bytes。命令目的地为0，header构造器对应 `HOST2N9`；这不是已验证的 CR4 memory reader。CR4地址能否经N9读取，取决于仍未取得的receiver实现。

## 输出和失败判定

结果通过 `printk` 写 kernel log，不通过 `iwpriv` get-buffer 返回。正常可见格式有16行，地址每次加4：

```text
addr 0xAAAAAAAA: 0xVVVVVVVV
```

每个 value按响应 buffer的 `[3],[2],[1],[0]` 顺序打印；重建原始 bytes 时，将该8位hex值按 little-endian 4 bytes写回。不能直接将显示的8位hex按字节顺序串接为文件。

输出条件是 `DebugCategory & 4 != 0` 且 signed `DebugLevel >= 0`。原始kernel数据里的初始值分别为 `0xc0077dff` 和1，满足条件，但运行时可被修改。不能把没有日志解释为地址不可读。

`show_mem_proc` 预先清零接收buffer，调用后不检查实际返回结果，并总是返回1。故 ioctl exit成功、16行全零或重复值均不足以证明读成功。应先保存同一单块的独立样本、确认地址/行数/无缺失及其与已知patch字节一致，再考虑后续区域。收集时保留command前后日志边界，不清空系统日志，不同时运行其他dump。返回的64 bytes可能涉及敏感材料，应只保存到仓库外。

host收到MCU响应不证明读到了ROM：receiver可能拒绝、返回错误、读取别名或仅支持特定RAM区域。真正ROM识别仍需结合映射、NDS32代码和跨样本一致性。

## 其他路径为何不能直接替代

- `RTMPIoctlMAC` / `mac` 处理的是host PCI register aperture。`mt_mac_cr_range_mapping` 对低于 `0x40000` 的值直接保留，随后走BAR直接读取；因此 `mac 0` 不是已经验证的 N9 ROM地址0读取。
- 对其他地址，MAC handler可能临时改写 remap register `BAR+0x2504`，通过 `BAR+0x80000+(address&0x7ffff)` 读取后恢复。它不是零配置写入路径；与并发driver访问的同步尚未建立。不要用无界地址范围命令做ROM dump。
- `dump_remap_cr_content` 支持 remap1/2，分别操作 `0x2500/0x2504`，也临时写寄存器。无效 selector分支甚至会将remap2置零，因此不将其列为首选只读诊断。
- `RTMP_IO_MCU_READ_BULK` / QA bulk路径是另一套寄存器请求及输出协议，尚未建立对ROM的有效映射，不应因名字含MCU便假定能读取整片ROM。

## 前提、未解及下一步证据

1. 需要已授权的本地 shell/console；本篇没有绕过管理认证的方法。
2. 确认实际driver/build、Wi-Fi interface和kernel log访问；`usr/sbin/iwpriv` 在已解rootfs中存在。
3. 只尝试已核对的单块查询并验证返回。不能在receiver行为未知时启动自动全地址扫描。
4. 成功读到patch后，仍需确认低地址常驻区域的映射、大小和读限制；得到ROM也不保证获得key，key可能由硬件内部提供。

## 证据索引

输入kernel SHA-256：`9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a`。
以下host代码地址的 file offset = VA − `0x81001000`；MCU地址不使用此公式。

| 位置 | 证据 |
|---|---|
| `ap_privtab@81693d10`，show记录 `81693d28` | ioctl `0x8bf1`，set_args `0x2400`，get_args0 |
| `RTMP_PRIVATE_SHOW_SUPPORT_PROC@81693910`，记录 `81693990` | name指针 `81600734`字符串 `dumpmem`，handler `812b14d0` |
| `rt28xx_ap_ioctl@81235200` / `RTMP_AP_IoctlHandle@81229440` | ioctl分发到case0x11及show parser |
| `RTMPAPPrivIoctlShow@812190c0` | `=`切分参数，字符串表查找handler |
| `show_mem_proc@812b14d0` | `812b14fc` hex解析；`812b1524` 调用dump；`812b1540–1550` log门槛；`812b158c–15a8`打印字节顺序 |
| 字符串 `81615b40` | `addr 0x%08x: 0x%02x%02x%02x%02x`，末尾换行 |
| `MtCmdMemDump@81348c80` | `81348d80/84`查询地址写payload；command0xed/ext0x57，目的地0；固定68 bytes |
| `CmdMemDumpRsp@8133b3d0` | response+4复制64 bytes |
| `AndesInitCmdMsg@81334358` / `AndesMTFillCmdHeader@81336cdc` | destination保存及header s2d；字符串 `HOST2N9@81610828` / `HOST2CR4@81610830` |
| `RTMPIoctlMAC@812a7204` / `mt_mac_cr_range_mapping@813775c0` | BAR直读与remap分支；不能等同MCU地址 |
| `dump_remap_cr_content@8129403c` | selector与remap临时写入、恢复/异常路径 |

原始C/ASM及hash清单只保存到私有 `mcu-dump-plan-20261112/interface/`，没有执行target、发包、改写寄存器或读取设备。
