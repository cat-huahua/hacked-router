# 静态 firmware 解码与代码导出

这些工具不执行目标程序，不连接设备，不写 flash。原始输出可能含固件内嵌凭据，必须放在 Git 外的私有目录；公开仓库只保留工具和脱敏结论。

## 解码已验证的 extender 嵌套包

```sh
python3 re_tools/decode_embedur.py /private/rootfs /private/new-agent-output
```

工具从已验证 build 的 `arc_swap` 读取 substitution table，验证包自带 SHA-256 和 BZip2 EOF，然后安全提取。拒绝未知 build、既有输出目录、路径穿越、链接和特殊文件。详见 [嵌套包证据](../docs/singtel-extender-embedded-agent-decode.md)。

Web wrapper 的静态展开：

```sh
python3 re_tools/decode_web_assets.py /private/rootfs /private/new-web-output
```

只处理已验证的 packer/template，不执行 JavaScript；未知候选保留原文。`eval` 候选也可能只是普通 runtime callback，不能据此断言加密。

## 全量 ELF 导出

准备独立安装的 Ghidra 和兼容 Java；没有自动安装或修改客户端配置。一次可输入外层 rootfs 和嵌套包，按 SHA-256 去重：

```sh
python3 re_tools/decompile_batch.py \
  --root /private/rootfs \
  --root /private/new-agent-output/root \
  --output /private/new-elf-batch \
  --ghidra /private/ghidra
```

`--output` 必须是新的 batch 目录；`--reuse /private/previous-single-file-export` 可复用 `decompile_firmware.py` 导出的相同输入、无函数失败且未分析超时的结果。`--workers 1` 可减少并行资源占用。自动分析默认每文件限600秒；每函数首次 decompile 限15秒，失败仍导出该函数的 assembly。超时不代表样本加密。

输出包括：

- `inventory.json`：全部输入路径、SHA-256、重复文件对应关系。
- `modules/<sha256>/`：pseudocode、assembly、逐函数结果与 summary。
- `coverage.json`：执行中的覆盖快照；`completed.json`：shard 全部退出后的快照。
- `projects/`：保留 Ghidra database，供后续针对失败函数重试。

`exported` 只表示已识别函数成功导出；`partial` 包括分析超时、函数失败或无已识别函数。缺少 artifacts、校验不一致与进程失败单独记录。**这些状态不证明所有 machine code 已识别，也不表示已逐函数人工验证。** Pseudocode 不是原始或保证可编译的源码。

批次结束后做独立核对与私有索引：

```sh
python3 re_tools/audit_decompile.py /private/new-elf-batch/modules
python3 re_tools/report_decompile.py /private/new-elf-batch
```

审计核对逐函数记录与 summary 计数、重复地址及输出文件，并保存输出 hash；它不验证 pseudocode 语义。文本脚本、HTML 与普通 JavaScript 本来就可直接读取，不需要 native decompiler。

首次函数超时后，可等对应 shard 完全退出，再在保留的 project 上使用
`-process '*.elf' -recursive -noanalysis -readOnly`，并以
`RetryFailedFunctions.java /private/new-elf-batch/modules /private/new-retry-output`
作 postScript。它只重试原索引中失败的函数，每函数120秒，输出独立结果，保留原始失败记录。
不要在仍由导入进程使用的 project 上启动另一进程。完成后可用
`report_decompile.py /private/new-elf-batch --retry /private/new-retry-output`
核对原始 summary/index hash 并生成包含重试的索引；不会覆盖原始导出。

## 已验证 kernel 的符号导入

```sh
python3 re_tools/we410443_kallsyms.py /private/raw-kernel /private/kernel-symbols
```

此工具固定到文档记录的 build14 kernel SHA-256；核对 token table、markers 与地址配对。`ImportKernelKallsyms.java` 用作 Ghidra preScript，参数是 `symbols.tsv` 和私有 `import-summary.json`。Raw loader 参数为：

```text
-loader BinaryLoader -processor MIPS:LE:32:default -cspec default -loader-baseAddr 0x81001000
```

不能把所有 `T/t` 符号都当函数：此 vendor kernel 也这样标记部分 init data。Importer 仅在所选代码范围 seed 函数，额外 exit-text 范围明确记为推断。符号导入成功与函数 decompile 成功分别记录。

本 build 的默认 Ghidra heuristic 曾把实际返回的 `printk` 误判为 no-return，截断普通调用后的控制流。新版 importer 因此禁用 `Non-Returning Functions - Discovered`，保留已知不返回函数分析。已有数据库的修复使用 `RepairKernelPrintkFlow.java`，只在分析副本中修正已证实的 printk 标记与普通调用；合法尾调用仍保留。`RestoreKernelSeedEntries.java` 按已验证符号补回缺失候选，遇到已有函数或 data 冲突则记录并跳过。这些操作改变分析数据库，不改变 firmware bytes；仍需核对实际 return、fallthrough 和函数覆盖。

## 验证工具本身

```sh
python3 -m unittest discover -s re_tools -p 'test_*.py'
```

Orchestration 测试使用 fake headless，不运行固件或依赖私有样本。实际 Ghidra 导出的覆盖范围另见 [覆盖记录](../docs/singtel-extender-decompile-coverage.md)。
