# WE410443-ST 解码与反编译覆盖范围

核对日期：2026-11-09；样本 v6.02.00 build14。本轮所有已枚举 ELF 和主 CPU kernel 已完成批量处理；这不等于所有代码已解密、所有指令都被正确识别或恢复了原始 C。

## 已完成的解码

- rootfs 完整提取：1247 files、98 directories、334 symlinks。原先“需要 flash AES key”的判断已被实际 decoder 修正，见 [解码证据](singtel-extender-crypto-path.md)。
- 内嵌 EmbedUR archive 经字节置换、BZ2 解压后提取 39 个文件，其中 15 个 ELF；decoded archive SHA 与厂商随包校验文件一致。见 [内嵌代理](singtel-extender-embedded-agent-decode.md)。
- 166 个 Web 文本文件中，4 个文件的 5 个编码块已静态展开，未执行目标 JavaScript；其余两个 eval 候选经人工检查属于普通运行时操作。
- kernel 解压，恢复 32,911 条 kallsyms 记录；符号数不等于函数数。
- TRX 九段区域连续覆盖全部输入，CRC 已验证；footer 的两个加密 envelope 和末尾版本记录已离线解码并核对 digest/CRC。中间 64,816 字节全零。见 [footer](singtel-firmware-footer.md)。

## ELF 批量反编译

rootfs 258 个 ELF 加内嵌包 15 个 ELF，共 273 条文件路径、按 SHA-256 去重后 266 个输入。使用直接 Ghidra headless：REA CLI 的旧 MIPS ABI admission 未通过，因此不称作 REA Evidence。

| 阶段 | 工具识别记录 | 自动 pseudocode 成功 | 失败 |
|---|---:|---:|---:|
| 首轮 266 个输入 | 92,084 | 92,060 | 24 |
| 对原失败项延长时间重试后 | 92,084 | 92,083 | 1 |
| dhcrelay 后续分析，单独列出 | 5,031 | 5,030 | 1 |

dhcrelay 首轮 5,029 条记录，autoanalysis 超时；后续 autoanalysis 正常完成，新增两条成功记录，没有删除旧入口。后续仍失败的 `dns_rdata_fromtext@004a089c` 已在首轮对应重试中成功，保留两次分析的独立来源，不伪造合并的单次运行统计。新增入口为 `0042482c`、`005e9dcc`。

唯一未成功的 ELF Ghidra 函数是 `_dl_load_elf_shared_library@00012cf4`。一次校正 base、GP/T9 的独立诊断仍得到 RAM 地址范围构造错误，不是加密证据。584 条线性 assembly 已逐条匹配输入；r2 pdc 提供补充阅读视图，但只有 579 个指令地址标记，另附遗漏 5 条，存在 103 个 orphan blocks，不能算完整 C 或额外 Ghidra 成功。

## kernel 反编译与校正

最初 Ghidra 错把实际会返回的 `printk@81526314` 标为 no-return，导致大量 caller 被截断。在私有分析副本中核对返回指令，恢复 8,768 个 JAL 的后继流，同时保留 348 个合法 J tail-call；重建 3,364 个 caller body，并补回经过核对的符号入口。初始导出已被 refined 结果替代，不与其重复相加。

| refined 导出 | 识别记录 | 自动 pseudocode 成功 | 失败 |
|---|---:|---:|---:|
| 导出 | 17,356 | 17,351 | 5 |
| 失败项重试后 | 17,356 | 17,354 | 2 |
| 排除已证实的数据误识别 | 17,355 | 17,353 | 2 |

`sys_call_table@810111f0` 被 vendor kallsyms 标成 T，但实际为 349 × 8 字节数据表；从代码候选统计中排除这一项，保留原始导出证据。第二个 word 的含义未定，不擅自命名为参数数。

剩余 `sys_syscall@81011188` 和 `MT_ATERDDParseResult@813f4ba0` 已补充逐指令 register-level pseudocode，包括 MIPS delay slots、tail dispatch、未对齐 LW 和重复全局读取；这是人工解释，不增加自动成功计数。

最初 kernel autoanalysis 达到 900 秒上限；refined 导出禁用了新一轮 autoanalysis，只执行明确的控制流修复及导出。因此不能把 refined 的 `analysis_timed_out=false` 解读为原始全量 autoanalysis 已完成。仍不能证明所有 machine code 已识别，或所有函数边界、类型、间接调用正确。

## 尚未解密与材料边界

- 内嵌 Wi-Fi MCU 的 N9、CR4 firmware：loader 明确设置加密下载标志，匹配 key 和完整 cipher 尚未确定，仍是密文。ROM patch 未设置该标志，但 ISA/入口布局未确认。见 [MCU 证据](singtel-extender-embedded-mcu.md)。
- bootloader 本体未包含在现有材料中，无法据此恢复完整 recovery 实现。
- pseudocode 不等于原始或可编译 C，尚未全部逐函数人工验证，也没有据此生成或验证可刷写的 OpenWrt 镜像。
- 本篇仅涵盖 extender 样本；主路由器独立 image_manager 容器问题不据此宣告解决。

## 证据索引

完整输出保留在私有 `router-notes-private/decode-all-20261109/`，可能含敏感字符串，不进入公开 Git。

| 证据 | 文件或符号 |
|---|---|
| 输入 TRX | SHA-256 `ac8b23b324798f6a52465b6d6857e4fa8297fbd6c2b602d69f13537ed73514df` |
| kernel 输入 | SHA-256 `9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a`；base `81001000`，uImage entry `81523eb0` |
| ELF 完整性核对 | `elf-batch/modules/export-audit.json`：266/266 对账；各模块 `summary.json`、`functions.jsonl`、`pseudocode.c`、`assembly.txt` |
| ELF 重试 | `elf-retry/*/retry-summary.json`，绑定原 summary/index SHA；`elf-batch/coverage-effective.json` |
| dhcrelay 补充 | `dhcrelay-analysis-continuation/comparison.json`，输入 SHA `2e7779e045cac5df2e812cd5e1bbf32bbec8406bbdf37ac2dc0f3a1de297b17e` |
| loader 诊断 | `loader-diagnosis/diagnosis.json`、`r2-pdc/coverage-audit.json`；输入 SHA `12306325f7d8852cfe15327ba527e0913ab29ddc526908fa4da1156273c95474` |
| kernel 首选导出 | `kernel/refined-decompiled/`、`kernel/refined-retry/`；`export-provenance.json` 保留基线超时信息 |
| 控制流校正 | `kernel/return-audit/`；`printk` 返回指令 `81526350`；未改写固件 bytes |
| 人工解释及数据排除 | `kernel/manual-fallback/evidence.json`、`known-data-reclassifications.json`；table 文件偏移 `0x101f0`，长度 `2792` |
| footer/web/MCU | `region-inventory.json`、`original-footer-verification.json`、`footer-version-tail-verification.json`、`web-tool-verified/`、`embedded-code/` |

所有“成功”仅表示该工具调用产生了 pseudocode，包含辅助函数、thunk 或尚未发现的误识别，不代表语义已验证。
