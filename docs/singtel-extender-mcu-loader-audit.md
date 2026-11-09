# WE410443-ST MCU loader：静态缺陷审查

本篇审查 v6.02.00 build14 的 N9/CR4 firmware 加载、长度解析和内存释放链。证据来自已校正 `printk` 控制流的 kernel pseudocode 与原始 assembly；没有运行目标、触发故障或制作 exploit。代码缺陷与攻击可达性分别记录，不能将下列问题称为已验证的远程利用链。

## 可达性边界

`mt7615_init` 将 firmware source mode 设为 **0**，复制到 adapter `+0x124549`。`AndesMTLoadFw` 仅在该字段为1时调用 `os_load_code_from_bin` 读取外部文件；默认0使用 kernel 内嵌数组。当前原厂 N9/CR4 的尺寸及 region 总长度已核对正常，见 [MCU 映像结构](singtel-extender-embedded-mcu.md)。

本轮对 preferred pseudocode 的直接字段赋值检索没有发现后续修改该字段的语句；这不是完整 alias-aware 证明。没有确认网络入口、非特权 source-mode setter 或外部文件替换途径。因此依赖 mode1、畸形文件或内存压力的结果只能标为**条件性缺陷**，不能据此承诺可用于恢复设备、绕过登录或刷入镜像。

## 已确认代码行为与条件性影响

| 编号 | 代码行为 | 触发前提与影响边界 |
|---|---|---|
| MCU-L1 | `fw_info` 未先检查 trailer 是否位于 blob 内；region 长度加4也未检查溢出 | 畸形 blob 必须先进入该 loader。可能发生越界读取、错误下载或 fault；未证实远程利用 |
| MCU-L2 | `os_load_code_from_bin` 忽略 `os_alloc_mem` 失败，直接调用 `memcpy` | 外部文件模式下第二次 allocation 失败，且文件非空，可能产生 NULL destination copy；默认内嵌路径不调用它 |
| MCU-L3 | 外部 N9 的活动指针被内嵌 CR4 替换，cleanup 仍以全局 source mode 决定是否释放 | mode1 的双核路径推进到 CR4 时，可能丢失 N9 allocation 并对内嵌 CR4 执行 invalid free；未证实 stock 配置可选择这种组合 |

### MCU-L1：trailer 与 region 源范围缺少检查

`fw_info(base,size,tail_offset,...)` 直接计算 `base + size - tail_offset`，从该位置 `-0x24..-1` 读取 trailer。N9 两次调用的 tail offset 分别为 `0x24` 和0，至少需要72 bytes；CR4 的一次调用至少需要36 bytes。解析末四字节后用 MIPS `addiu ...,4` 加 CRC 大小，是 wrapping 32-bit arithmetic；不能把 pseudocode 的 signed 类型当成已验证的 C 原型。

调用链没有在 scatter 前验证 region 长度、总和及源范围是否在 blob payload 内。`MtCmdFwScatters` 将传入长度切为小块，`MtCmdFwScatter` 为每块分配消息 buffer，随后 `AndesAppendCmdMsg` 执行复制。这种分块限制了单个目标消息的尺寸，**没有验证源 buffer 的剩余长度**。

条件满足时可能先出现 trailer under-read，或将源 buffer 外的内存读入 MCU 命令、fault、长时间下载；实际结果取决于内存映射及命令返回，未证明向网络泄露数据或代码执行。

修复建议：任何读取前验证 trailer 最小长度；使用 checked unsigned arithmetic；验证每个 region 与总 payload 范围后再发送 MCU 命令；在 MCU 密码校验之外独立完成 host-side 输入验证。

### MCU-L2：忽略 allocation 失败

`os_alloc_mem` 将 `__kmalloc` 结果写入输出指针，结果为0时返回失败。`os_load_code_from_bin` 检查了 `request_firmware`，却未检查后续 `os_alloc_mem` 的返回值或输出指针，直接复制完整文件长度。第一次文件加载成功不能保证第二次 allocation 成功。

修复建议：检查 allocation 状态与指针，失败时释放 `request_firmware` 资源，清空输出指针/长度并传播错误。

### MCU-L3：N9/CR4 指针所有权混用

N9 启动成功后，loader 将 adapter `+0x124578` 中的内嵌 CR4 指针写入活动槽 `+0x12454c`，在这条成功边上未释放外部 N9 allocation。CR4 下载/启动失败，以及启动成功后的共同结束路径，都能进入 `NICEraseFirmware`。

`AndesMtFwdlHookInit` 安装的 callback 是 `AndesMTEraseFw`。该函数只检查 source mode 是否为1，再释放活动槽当前指针；`os_free_mem` 尾调用真实 `kfree`。它没有区分“该指针来自 allocation”还是“内嵌 CR4 array”。因此在 mode1 且推进到 CR4 的路径上，静态代码存在 ownership mismatch。当前默认 mode0 不进行该释放；是否有合法外部配置能进入 mode1 尚未确认。

修复建议：为每个 core 分开保存不可变 source、owned allocation、长度与 ownership flag；替换活动指针前处理旧 allocation；所有错误出口只释放 owned memory。

## 关联问题与未解

CR4 reset-IV 控制位读取第一段 N9 feature，而 CR4 自身 encryption/key-index 来自另一个字段。两份 stock feature 均为1，掩盖了这种不一致，详见 [解密链与 IV 证据](singtel-extender-mcu-decrypt-path.md)。这不构成 key 恢复或加密绕过。

尚未完成：source-mode 全别名写入分析、外部入口可达性、runtime crash 验证、MCU 解密实现及完整安全审查。本篇没有 CVE 归属结论，也不宣称找到了所有 bug。

## 证据索引

输入 raw kernel SHA-256 已再次核对：
`9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a`。
地址规则 `file offset = VA - 0x81001000`。私有原始证据位于
`router-notes-private/decode-all-20261109/kernel/refined-decompiled/`；补充核对记录为
`router-notes-private/mcu-followup-20261109/parser-audit.md`。

| 符号 / VA | 证据 |
|---|---|
| `mt7615_init@81320e64` | `81321044` 将0写入模板+0x109；`8132122c` 将模板复制到 adapter+124440，得到 source mode +124549=0 |
| `fw_info@8134f620` | `8134f628/650` 计算 trailer 位置，`8134f65c–668` 开始读取；`8134f794` 长度加4，`8134f798` 写出 |
| `MtCmdFwScatters@8134fabc` / `MtCmdFwScatter@813493d4` | 依据传入总长度分块并复制，不接收独立 blob source bounds |
| `AndesAppendCmdMsg@8133445c` | `81334498` 尾调用 `memcpy@8116ca40` |
| `os_alloc_mem@813c6e74` | `__kmalloc` 返回值写入输出，NULL 表示失败 |
| `os_load_code_from_bin@813c6ea8` | `813c6f34` allocation；`813c6f40` 加载目标指针；`813c6f48` 无失败分支即调用 memcpy |
| `AndesMTLoadFw@8135001c` | `81350ff0/ffc` 用 CR4 指针覆盖活动槽；CR4 sync 成功 `813515f4`、超时 `813515c8` 均跳到共同 cleanup |
| cleanup `813509e4–81350a00` | 非空活动槽在 `813509f8` 调用 `NICEraseFirmware@81358608` |
| `AndesMtFwdlHookInit@81352968` | `81352988–8135298c` 安装 `AndesMTEraseFw` cleanup callback |
| `AndesMTEraseFw@8134ffb0` | `8134ffc8–ffd0` 检查 mode1；`8134ffe8` 取当前指针；`8134fff4` 调用 os_free_mem |
| `os_free_mem@813c6f98` | `813c6fb8` 尾调用 `kfree@810c38f8` |
