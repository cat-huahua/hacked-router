# WE410443-ST：N9/CR4 解密边界与 host 下载路径

核对日期：2026-11-09。沿 [内嵌 MCU](singtel-extender-embedded-mcu.md) 的 blob 消费链继续追踪，目标是区分 host 解密、host 传递 key，以及 MCU 侧解密。本篇是静态证据，没有执行 firmware、访问设备或证明 MCU 实际执行结果。

## 已解：host 发送加密格式的原始 payload

已核对的路径为：

```text
mt7615_fw_prepare / mt7615_init
  → AndesMTLoadFw → fw_info
  → MtCmdAddressLenReq(address, length, mode)
  → MtCmdFwScatters → MtCmdFwScatter
  → AndesAppendCmdMsg → skb_put + memcpy
  → AndesSendCmdMsg → AndesMTFillCmdHeader
  → AndesMTPciKickOutCmdMsgFwDlRing
  → RTMP_QueryPacketInfo → RtmpDrvPciMapSingle → PCI DMA ring
```

`MtCmdAddressLenReq` 分配 12-byte payload，依次 append 三个 32-bit word：download address、download length、download mode。这个命令中没有额外 key buffer；key-index 是 mode 的 bits 2:1，不是 key 内容。`MtCmdFwScatters` 按 `0x1000 - adapter_byte` 限长切块；`MtCmdFwScatter` 把原 region 指针与 chunk 长度交给 `AndesAppendCmdMsg`。后者执行 `skb_put` 后 `memcpy`，没有在该拷贝路径执行 payload 解密。

关键间接调用也已跟到该 build 的赋值点：

| adapter offset | 已确认的 callback |
|---|---|
| `+0x1243e0` | `AndesSendCmdMsg` |
| `+0x1243bc` | `AndesMTFillCmdHeader` |
| `+0x1243b8`，N9/CR4 download 阶段 | `AndesMTPciKickOutCmdMsgFwDlRing` |

`AndesMTFillCmdHeader` 前置命令/transport header；未在所读函数内修改已有 payload 内容。下载 ring 函数查询 packet data/length，将该 buffer DMA map，并填充 descriptor 与 producer index。N9 完成后 `AndesMTLoadFw` 将当前 blob pointer 换成 CR4 blob，再走相同发送链。

**推断：** 在这个具体加载路径，解密责任位于 MCU 下载接收端，而非 MIPS host 的上述发送链。接收方的 ROM/硬件实现当前未提供，故不能进一步断言 cipher 是 AES、RC4 或某种模式，也不能定位 key 到 ROM、eFuse 或 flash。这里没有凭借存在 `ARC4_INIT`、`AES_*` 等通用/Wi-Fi 加密符号就把它们当作 MCU 解密器。

**有界否定：** 上述逐函数路径未找到 host key 装载或 payload 解密；不等价于证明整个 kernel/SoC 不存在其他访问 key 的机制。完整的 MCU 接收端实现与运行时行为仍未知。

## 已排除的 crypto 符号混淆（有界搜索）

对 refined pseudocode 中可解析的直接调用进行核对，所发现的 `ARC4`/`AES` 解密调用分别落在 WEP/TKIP、CCMP、AES primitive/key unwrap，以及 WPS `ProcessMessageM4` 到 `ProcessMessageM8` 等路径；没有在上述 loader 调用链找到它们。此检查只覆盖已导出的直接调用表达式，不排除未恢复的间接调用、匿名实现或硬件。

`MtAsicAddRemoveKeyTabByFw@81328b30` 也不是 firmware image 的 key setter：它根据传入的 cipher/key 信息构造 WTBL 更新记录，调用 `CmdExtWtblUpdate`，属于无线数据加密 key table 路径。这里的 “ByFw” 表示经 firmware 更新表，而非解密 firmware 自身。未公开任何实际 key 值。

Linux 官方 [v6.12 mt76_connac_mcu.h](https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/net/wireless/mediatek/mt76/mt76_connac_mcu.h) 可交叉核对 ENCRYPT、key-index、reset-IV 位定义；同一公共头文件里较新 chip 的 AES 定义不能直接用来认定 MT7615 本样本的 cipher。

## 已确认的逻辑不一致：CR4 reset-IV 使用 N9 feature

`AndesMTLoadFw` 的双核路径分别由 `fw_info` 保存三个 feature byte：N9 region 0 到 `sp+0x25`，N9 region 1 到 `sp+0x24`，CR4 到 `sp+0x23`。

CR4 的 mode 构造中：

- `0x81351054` 从 `sp+0x25` 读取 **N9 region 0** feature，用 bit 0 决定是否加入 `0x8` reset-IV。
- `0x81351058` 从 `sp+0x23` 读取 **CR4** feature；`0x8135106c` 取 low 3 bits，形成其 ENCRYPT/key-index。
- `0x81351084` 调用 `MtCmdAddressLenReq`，delay slot `0x81351088` 合入 reset-IV。

即实现为：

```text
CR4_mode = 0x80000010 | (CR4_feature & 7)
           | ((N9_region0_feature & 1) ? 8 : 0)
```

按同一 region 的 encryption flag 决定 reset-IV 的一般语义，应该检查 CR4 自身 bit 0；这是**数据来源不一致的静态事实**，并非 decompiler 变量名推断。当前原厂样本三个 feature 都为 `0x01`，因此这个差异不改变本样本 mode，仍为 `0x80000019`。

**影响边界：** 当 N9/CR4 encryption flag 不同时，host 发出的 reset-IV 会与 CR4 自身 encryption flag 不一致。是否造成下载失败或其他效果取决于 MCU 接收端，尚未运行验证。没有发现外部攻击者能修改这几个内嵌 blob 的已验证入口；本结果不构成远程利用、认证绕过或 key recovery 证明。建议源代码修复时使用 CR4 feature，并在离线单元测试覆盖两种 flag 不一致组合。

## 未解

- 匹配的 MCU key、实际 cipher/初始化规则，以及 MCU 下载接收端代码。
- ROM patch 后续已识别 NDS32 代码并导出候选函数，见 [patch 分析](singtel-extender-rom-patch.md)；完整 entry layout、外部 ROM 与处理器端语义仍未恢复。
- 当前已能解释 host 如何要求解密与发送 ciphertext，尚不能生成解密后的 N9/CR4 code。
- 发送链之外的匿名数据、间接调用和外部硬件功能不在本篇已排除范围内。

## 证据索引

输入 kernel SHA-256：`9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a`。
映射 `file offset = VA - 0x81001000`。以下为 refined Ghidra export 与原始 kernel bytes 对应证据；pseudocode 类型仍可能有误，以 assembly 数据流为准。

| 符号/位置 | VA | 证据 |
|---|---|---|
| `ChipOpsMCUHook` | `0x81333f10` | 发送、header、download ring callback 赋值 |
| `AndesMTLoadFw` | `0x8135001c` | N9/CR4 指针、region 解析、mode 和启动命令 |
| N9 feature 目的地址 | `0x81350698–0x813506b0` | `sp+0x25` 作为 `fw_info` 第六参数 |
| CR4 feature 目的地址 | `0x81351038–0x81351050` | `sp+0x23` 作为第六参数 |
| CR4 mode 来源不一致 | `0x81351054–0x81351088` | N9 决定 bit 3，CR4 决定 bits 2:0 |
| `MtCmdAddressLenReq` | `0x81349208` | 三次 4-byte append；调用点 `0x8134931c/30/44` |
| `MtCmdFwScatters` / `MtCmdFwScatter` | `0x8134fabc` / `0x813493d4` | 原 buffer 切块后 append；scatter command id `0xee` |
| `AndesAppendCmdMsg` | `0x8133445c` | `skb_put` call `0x8133447c`；`memcpy` tail jump `0x81334498` |
| `AndesInitCmdMsg` | `0x81334358` | 命令 id/flag 与 queue metadata |
| `AndesSendCmdMsg` | `0x813354a0` | queue/header callback/kick-out callback |
| `AndesMTFillCmdHeader` | `0x81336cdc` | 前置 header，没有已确认的 payload 解密操作 |
| `AndesMTPciKickOutCmdMsgFwDlRing` | `0x813369d4` | data/length 查询、DMA map、descriptor 与 ring producer |
| `RtmpDrvPciMapSingle` / `RTMP_QueryPacketInfo` | `0x8135ce50` / `0x813c5914` | DMA wrapper、packet pointer/length 读取 |

私有证据在 `router-notes-private/mcu-followup-20261109/key-path/`：17 个选定函数的 assembly/pseudocode 分片，以及 `evidence.json` 中的源 SHA、入口、指令数和分片 hash。原始导出、潜在敏感字符串不进入公开仓库。

补充私有证据：`mcu-followup-20261109/cr4-flag-raw-check.json` 独立解码关键 MIPS 指令字；`crypto-call-candidates.json` 与 `crypto-exclusions/` 记录直接 crypto 调用搜索边界及排除依据。
