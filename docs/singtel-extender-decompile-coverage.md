# WE410443-ST 解码与反编译覆盖范围

核对日期：2026-11-09。样本：v6.02.00 build14。提取、反编译和逐函数理解是三个不同阶段。

## 已完成

- rootfs 已完整提取：1247 files、98 directories、334 symlinks；原先认为需要 flash AES key 的判断已被实际 decoder 和提取结果修正。见 [解码证据](singtel-extender-crypto-path.md)。
- kernel 已解压，可做静态分析；这不等于整个 kernel 已反编译。
- 本轮六个 ELF 已通过直接 Ghidra headless 导出 pseudocode、assembly 和函数索引。REA CLI 的旧 MIPS ABI admission 未通过，所以这些结果不是 REA Evidence。

| ELF | 识别函数 | 成功导出 pseudocode | 失败 |
|---|---:|---:|---:|
| `usr/sbin/autofw` | 193 | 193 | 0 |
| `usr/sbin/uboot_env` | 84 | 84 | 0 |
| `sbin/arc_owl_fwupgrade` | 246 | 246 | 0 |
| `sbin/arc_uploadhelper` | 204 | 204 | 0 |
| `usr/sbin/httpd` | 816 | 816 | 0 |
| `usr/lib/libArcOWLcore.so` | 1284 | 1284 | 0 |

合计 2827 个已识别函数成功导出。函数计数包含工具识别的辅助函数/thunk，不能当成完整业务函数数，更不证明所有 machine code 已覆盖。

## 未完成与材料边界

- 其余 ELF 尚未全部批量反编译；本轮六个 ELF 的 pseudocode 也没有全部逐函数人工验证。
- pseudocode 不是原始 C 源码；类型、变量名、间接调用目标仍可能需要人工校正。
- 现有升级包没有提供可供验证的完整 bootloader 本体，不能据此声称恢复了 bootloader 口令或 recovery 实现。
- 主路由器 EmbedUR `image_manager` 的独立加密容器/key 问题仍未解决，见 [容器分析](singtel-embedur-image-format.md)。它与本篇已解出的 extender rootfs 是不同材料。
- 解出 rootfs 不表示已经生成或验证可刷写的 OpenWrt/custom 镜像。

## 证据索引

本地私有输出目录为 `router-notes-private/decompiled-extender-20261109/`；每个模块包含 `summary.json`、`functions.jsonl`、`pseudocode.c`、`assembly.txt` 和 `headless.log`。原始导出可能含敏感字符串，不进入公开仓库。

| 输入 ELF | SHA-256 |
|---|---|
| `usr/sbin/autofw` | `8933428ea737eab326bae33b9bf69ecf5cdd12749fe1c0dc3235e82a38154027` |
| `usr/sbin/uboot_env` | `0e075af602bfb9b648268c354d60eb25393bccbbaee21226499631ab29a24553` |
| `sbin/arc_owl_fwupgrade` | `b97cf9fe005ae38263b1a80f9453071b86a91123bc6ec03e7ee9b95d9553a5a1` |
| `sbin/arc_uploadhelper` | `3e8c63e6ec8949adbc480f01b4af05c21e6f29ab3216d836052ec77c2d8d1814` |
| `usr/sbin/httpd` | `f0e4028bb4ced6c08615828e274b3e77f6d94ac9d08957560021cc369cdf553e` |
| `usr/lib/libArcOWLcore.so` | `a82215914ea90267887f73a4f7499ad61b3e3b5ea6836cc050901109b1c43eed` |

`coverage.json` 六项 exit_code 均为 0，summary 中 `all_machine_code_proven_covered` 均为 false。独立核对样例：`autofw:is_got_ntptime` VA `0x401d6c` 的 pseudocode 检查参数 `+0x14` 是否不等于 `0x46`，与既有 MIPS assembly 的年份判断一致；单函数吻合不能代替全体人工验证。
