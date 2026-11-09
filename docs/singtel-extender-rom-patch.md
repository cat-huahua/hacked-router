# WE410443-ST ROM patch：NDS32 解码与 key 搜索边界

2026-11-09 继续检查原厂 MT7615 ROM patch。此次确认了可解释的 NDS32 指令、表内入口候选和部分 callback，产出私有 pseudocode；**没有找到可验证的 N9/CR4 firmware key 或完整解密实现**。静态 patch 不等于完整 MCU ROM，未访问设备或执行目标代码。

## 已解：payload 是代码、表和数据的混合体

外层 blob 为11,102 bytes，去掉30-byte header后得到11,072-byte payload。host 下载地址为 `0x80000`，本次沿用这个地址映射；它不是已验证的启动 entry。

payload 首部包含 little-endian word 表及大量零字节。`+0x108..+0x14c` 的18个 word 中，17个指向 payload 内部，例如 `+0x14c → 0x80540`，另一个为外部地址 `0x1d28c`。不能把表头 `0x80000` 当作指令入口。

ISA 判断由以下联合证据支持，不再只靠 N9 名称推测：

- 内部表指针目标按 **NDS32、little-endian data / big-endian instruction** 解码，得到连贯的栈保存、参数访问、分支和 return。
- `0x80540` 的 `smw.adm` 栈保存及后续寄存器运算，可由 Ghidra 与独立 r2/binutils disassembler 互相核对。
- `0x81414` 起的 wrapper 保存寄存器并访问 `PSW`、`IPC`、`IPSW`，符合 NDS32 异常处理代码；多个相邻表目标具有同类结构。
- `sethi` / `ori` 形成的绝对地址能落到 payload 内的 debug 字符串，字符串语义与调用点相符。

采用本机 Ghidra 12.1.4 的 `NDS32:LE:32:default`，不强行套用主 CPU 的 MIPS ISA。ROM patch 的 ISA 证据不能自动证明尚未解密的 N9/CR4 每段 code 的实际启动状态。

## 已解：有限的代码导出与功能类别

| 分析阶段 | 候选来源 | 工具识别记录 / pseudocode 成功 |
|---|---|---:|
| 首轮 | 17个表内目标及自动发现 | 34 / 34 |
| callback 补充 | 初始化函数写入的6个代码地址 | 40 / 40 |
| 有界扩展 | 未覆盖区域中10个对齐 NDS32 栈保存序言候选及自动发现 | 55 / 55 |

后两阶段包含前阶段结果，**不能相加**。最后阶段的序言识别是明确标注的推断，不证明所有入口或边界正确；成功指工具产生文本，不是完整原始源码。初版、callback版与expanded版分别保留。

已读路径主要涉及初始化、UART/debug 输出、异常寄存器保存/恢复、debug callback 调度、部分硬件/MAC寄存器更新。比如表候选 `0x80f98` 调用初始化例程并写入多个 gp-relative callback，`0x82078` 安装 `0x820d4` callback。`0x8149c` 等路径使用 register-dump 类格式字符串。没有将这些类别或 callback 操作表称为 firmware decryptor，也没有根据 debug 功能推导出可远程读取 key 的入口。

## 对 key 搜索的意义与未解

部分调用直接进入本 payload 之外的低地址；另外大量 callback 通过 `gp + offset` 间接取得。当前 **gp 实际值、运行时 callback 表内容、外部目标 bytes 均未取得**。因此不能仅凭该 patch 判断外部处理器代码如何解密 firmware。

可识别的直接外部调用目标（MCU 地址，非 host kernel VA）：

```text
0x00000560  0x0000058c  0x00000e80  0x00001344  0x00002204  0x00002cb4
0x000058d4  0x00005e80  0x000069c8  0x000069d8  0x00006a5c  0x00006ab4
0x000098cc  0x00009900  0x0001d024  0x0001d078  0x0001d2cc  0x000225a0
```

这些目标可能位于 ROM 或其他常驻映像，属于**推断**；本样本未包含对应地址的 bytes，无法将其命名为 AES/RC4/key-loader。对已导出代码的检查未识别出可信的 firmware 解密函数或匹配 key，不能扩展成“整个 MCU 没有 key”。

仍未解决：完整 MCU ROM、gp/callback 初始化来源、firmware 解密算法及 key、所有未识别 leaf functions 与数据语义。当前的 N9/CR4 RAM firmware 仍为加密格式，详见 [host 解密边界](singtel-extender-mcu-decrypt-path.md)。

## 工具与校验限制

- Ghidra 的 `addi.gp` 显示缺少 operands，但本机 SLEIGH 定义含 `Rt = gp + Imm19s` 语义。需要结合原始 bytes / 第二个 disassembler 核对；未知 gp 仍会在 pseudocode 中保留为 `unaff_gp`。
- r2 的 NDS32 某些后向分支显示超过32-bit的目标，例如本应回到 `0x8021a` 的 branch；它不是实际 MCU 地址。分支应对照原始编码及 Ghidra，不能照抄为 ROM 入口。
- pseudocode 存在 global overlap、未解析调用和类型推断限制。没有全指令覆盖保证，没有在错误地址空间中补造 ROM bytes。
- 独立核对发现 payload 的16-bit one's-complement sum 与 header checksum匹配（BE word计算得到 `0x4b61`，LE表示为 `0x614b`）。这是算法匹配证据，不是数字签名、完整性安全保证或解密成功证明。

## 证据索引

| 证据 | 位置 / 身份 |
|---|---|
| 原始 ROM patch | kernel file `0x699bb0`，11,102 bytes；SHA-256 `bc13aac3d139f4554d51b25799f1f2fbb00aaae102d2ae3a7687d344d94abd08` |
| payload | blob `+0x1e`，11,072 bytes；SHA-256 `b145d9ac65634960e0ffe4dffb126bd305a92017e72576ef41f771ab827ddb12` |
| 地址换算 | MCU VA = payload offset + `0x80000`；kernel file offset = payload offset + `0x699bce` |
| 内部候选表 | payload `0x108..0x14c`，17内部/1外部 word |
| 指令核对样例 | MCU `0x80540` 栈序言；`0x81414` 异常 wrapper；`0x80208` 初始化拷贝循环 |
| callback 注册 | MCU `0x80f98`、`0x82078`；未知 gp 保留，不猜绝对表地址 |
| 私有分析来源 | `mcu-rom-followup-20261109/rom/seeds.json`、`callback-seeds.json`、`prologue-seeds.json`、对应 headless logs |
| 首选私有导出 | `rom/expanded-decompiled/{summary.json,functions.jsonl,pseudocode.c,assembly.txt}`；`rom/analysis-summary.json` 保存 hash 与范围 |
| 外部 flow | `rom/external-direct-flow.json`，记录30个外部直接 transfer 位置 |
| checksum 独立模型 | `cipher-patterns/patch-checksum-hypothesis.json`，不改变原始样本 |

所有原始代码、字符串及潜在敏感常量保留在仓库外私有目录；公开文档不包含 key 值。
