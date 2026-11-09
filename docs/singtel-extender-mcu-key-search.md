# WE410443-ST：下载前初始化与 MCU key 搜索边界

核对日期：2026-11-09。继续检查 [N9/CR4 下载链](singtel-extender-mcu-decrypt-path.md)之前的 host 初始化，以及 EEPROM/eFuse、reset 和 ownership 函数。尚未找到匹配 image key 或 host firmware 解密器；本篇记录进一步排除的具体路径，不声称遍历了所有代码或证明 key 不在硬件中。

## 已解：常规 EEPROM 初始化在 MCU 加载之后

`WfInit` 的成功路径依次执行 TOP、HIF、MCU、校准缓存应用、EEPROM、MAC/BBP 初始化。`WfMcuInit` 内部则先加载 ROM patch，再加载 N9/CR4。常规 EEPROM 参数读取在此路径中晚于两份 firmware 的下载，不能把它自动当成 host 下载前的 key provisioning。

| 调用点 | 目标 |
|---|---|
| `0x8128a3d0` | `WfMcuInit@81289f38` |
| `0x81289fb0` | `NICLoadRomPatch@813584e0` |
| `0x8128a058` / `0x8128a0c0` | `NICLoadFirmware@81358574` |
| `0x8128a40c` | `rlmCalCacheApply@8134ac14` |
| `0x8128a414` | `WfEPROMInit@8128a2a4` |

这是该控制流的顺序，不排除更早的其他 caller、MCU 自行访问 eFuse，或 hardware reset 时内部装载 key。

## 已解：两个下载前 callback 的真实目标

`mt7615_init` 在 `0x81321244` 把 `0x81839380` 起 `0x1bc` bytes 的 ops 模板复制到 adapter `+0x124284`。

| adapter slot | 模板偏移 / 赋值指令 | 实际目标与作用 |
|---|---|---|
| `+0x1243e4` | `+0x160`；`0x813210e0–0x813210e8` | `mt7615_fw_prepare@8131cc98`，选择 blob 指针和尺寸 |
| `+0x12443c` | `+0x1b8`；`0x81321214–0x81321230` | `mt7615_hif_set_pcie_read_params@8131ca0c`，PCI 参数设置 |

第二个函数对 MMIO-relative offsets `0x6088/0x7014/0x7110/0x4260` 做固定 mask/OR；所读实现没有 key buffer读取、key word写入循环或 crypto 调用。不能只因存在 MMIO 写入就将其认定为 key provisioning。

## 已解：control、DMA、reset 与 ownership 的排除范围

`ChipOpsMCUHook` 绑定 `AndesCtrlInit` 和 `AndesMTPciFwInit`。前者初始化消息 queue、tasklet、状态；后者执行 PCI DMA reset、可选 enhanced PDMA、interrupt registers 设置及 DMA enable。检查相应函数，没有发现 firmware payload crypto 或可识别的 image-key buffer 装载。

`AndesResetMcuViaWdt` 清控制位，经 MMIO remap 向地址 `0x81080044` 写标量常量 `0x1209`，再等待 firmware sync。这个常量出现在 watchdog reset 路径；没有证据将其当作 key。`AndesRestartCheck` 可调用零长度 payload 的 `MtCmdRestartDLReq`。该 build 的 `MtCmdPowerOnWiFiSys` 仅返回0，`MtAsicTOPInit` 仅返回1，不能根据函数名假设它们执行了隐藏初始化。

`FwOwn` / `DriverOwn` 的可读实现涉及 host/firmware ownership、等待与 reset fallback，未发现 image-key 数据装载。这里没有给全部 MMIO 位赋予未经验证的硬件语义。

## eFuse 符号仍不能定位 image key

- `mt7615_bufferModeEfuseFill` 将 adapter `+0x1247d6` 起 `0x38c` bytes 复制到命令数据区。
- `MtCmdEfuseAccessRead` 构造24-byte access请求，对请求地址做16-byte对齐，再经 callback取得返回值。
- `eFuse_init` 检查可用块数并选择 EEPROM buffer/file/eFuse 模式。

这些是实际 eFuse/EEPROM 功能，但尚未建立它们向 MCU firmware decoder传 key 的调用或数据流。既不能把其 buffer 当作已恢复的 key，也不能据此断言 key 不在 eFuse：MCU内部读取和硬件读保护都不在 host证据范围内。

## 未解

匹配的 N9/CR4 key、cipher、初始化规则、MCU下载接收端实现仍未恢复。匿名实现、未解析间接调用和实际硬件行为未穷尽。此轮仅为静态分析，没有执行目标、读取设备或改写 firmware。

## 证据索引

输入 raw kernel SHA-256：`9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a`。
地址换算：`file offset = VA - 0x81001000`。34个选定函数的 C/ASM 分片、源 hash 和关键原始指令检查保存在私有 `router-notes-private/mcu-rom-followup-20261109/host/evidence.json`，解释见同目录 `FINDINGS.md`。原始代码可能含敏感字符串，不发布。

| 符号 | VA | 本轮用途 |
|---|---|---|
| `WfInit` / `WfMcuInit` / `WfEPROMInit` | `8128a328` / `81289f38` / `8128a2a4` | 初始化先后顺序 |
| `mt7615_init` | `81320e64` | callback模板赋值与copy |
| `AndesCtrlInit` / `AndesMTPciFwInit` | `81334fb4` / `813377f0` | queue与DMA初始化 |
| `PciResetPDMAToMakeSurePreFetchIndexCorrect` / `EnhancedPDMAInit` | `81321ba4` / `81321c50` | DMA相关写入 |
| `AndesMtFwdlHookInit` / `AndesResetMcuViaWdt` | `81352968` / `8134f8c0` | reset callback和实现 |
| `AndesRestartCheck` / `MtCmdRestartDLReq` | `8134fbd4` / `813490ec` | restart命令无key payload |
| `MtAsicGetFwSyncValue` | `81326950` | 读取MMIO+1134 |
| `MtCmdPowerOnWiFiSys` / `MtAsicTOPInit` | `8134bbc0` / `813275d8` | 实际为常量返回stub |
| `FwOwn` / `DriverOwn` | `8135d6f4` / `8135d864` | ownership等待/reset路径 |
| `mt7615_bufferModeEfuseFill` / `MtCmdEfuseAccessRead` / `eFuse_init` | `8131c9b0` / `8133e7a8` / `81367a3c` | EEPROM/eFuse路径有界排除 |

## 密文模式的补充检查（非 key 恢复）

按 region 起点对齐后，三个 download region 长度均为16-byte倍数，而且最常见的
16-byte块相同。仅统计相等关系，不公布该块或把它命名为密钥：

| region | 最常见块出现次数 | 最长连续相同块数 |
|---|---:|---:|
| N9 region0 | 1351 | 1257 |
| N9 region1 | 137 | 84 |
| CR4 region0 | 6 | 4 |

这支持继续研究16-byte粒度的确定性转换，但不能单独证明 AES/ECB、明文为零、key长度
或 reset-IV 的真实硬件语义。以“该块对应全零”为假设做一次循环 XOR 检查，未得到
可信文本/代码恢复，也未匹配所试的末4-byte CRC32假设；这些假设结果没有被计作解密成功。
不匹配不能排除其他 CRC布局或密码算法。私有 `cipher-patterns/report.json` 与
`xor-hypothesis.json` 记录输入身份、计数及实验边界。

公开的 [cyrozap 原始研究笔记](https://github.com/cyrozap/mediatek-wifi-re/blob/master/Notes.md)
也描述过其他 MediaTek 芯片上的 PDA 与16-byte操作，但其 MT7697/手机 SoC实验不能
替代本 MT7615样本的算法或 key证据。本轮没有套用其他产品的 key 或声称其硬件映射相同。
