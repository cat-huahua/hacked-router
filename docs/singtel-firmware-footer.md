# Arcadyan 固件尾部：HDR0 envelope 与 legacy trailer

材料：主路由 WG9116AEAC23-ST 的 `libcms_util.so` / `libbcm_flashutil.so`，
以及 extender `WE410443-ST_v6.02.00_build14.trx`。
**代码中的格式与另一型号的实际样本分开记录，不能直接认定跨型号兼容。**

## 已解：64 KiB 区域开头的 0x290 字节

主路由 `arca_validateImage` 的非 BCM-tag 路径先调用内部 helper VA `0x11f78`
（此函数在导出符号中无名；原文档称 `arca_verifyDigitalSignature` 是用途标签）。
helper 从 `T = image_length - 0x10000` 复制 `0x290` 字节：

| 相对 T 偏移 | 长度 | 使用方式 |
|---|---:|---|
| `0x000` | 4 | 本 helper 没有读取其语义；样本为 0 |
| `0x004` | 4 | little-endian covered length，第二次 SHA-256 的输入长度 |
| `0x008` | 4 | little-endian key index，用于选择 payload envelope 的内置 key slot |
| `0x00c` | `0x140` | region envelope |
| `0x14c` | `0x140` | header envelope |
| `0x28c` | 4 | ASCII `HDR0`；按 H / D / R / 0 四个字节检查 |
| `0x290–0xffbf` | `0xfd30` | 本 helper 不读取；样本逐 byte 核对为全零 padding |
| `0xffc0–0xffff` | `0x40` | 本 helper 不读取；extender 的 OWL updater 读取为版本尾记录，见文末 |

helper 检查 key index 不大于 6，且 covered length 不大于传入 image length。
注意代码只检查上界，不能将其改写成已严格验证 `1 <= index <= 6`；
正常选择逻辑按 1–6 使用六个 slot，header envelope 固定使用第一个 slot。

### 每个 0x140 字节 envelope

helper VA `0x11dd0` 对两个 envelope 使用同一布局：

| envelope 相对偏移 | 长度 | 含义 / 证据 |
|---|---:|---|
| `0x000` | `0x38` | 对称密文；分两次 0x18 和一次 8 字节送入 `R_OpenUpdate`，再 `R_OpenFinal` |
| `0x038` | `0x100` | 传给 `R_OpenInit` 的 RSA 包装密钥块 |
| `0x138` | 8 | 传给 `R_OpenInit` 的 IV |

`R_OpenInit` 以 algorithm id 3 调用；内部先 `RSAPrivateDecrypt` 解包装，
要求会话密钥长 24 字节，随后走 `DES3_CBCInit`。因此这里是 RSA 包装会话密钥
加 Triple-DES-CBC 的 envelope，**不是简单的“64 字节 RSA 签名”结构**。
库内 key slot 的材料仅在本地核对，不在公开仓库保存任何 key 字节或提取产物。

### 两轮摘要比较

1. 先解 header envelope；计算 `SHA256(T[0:0x14c])`。
2. 逐个 32 位 word 比较输出与计算摘要，循环终值是 `0x14`，即仅比较前 20 字节。
3. 按 index 选 slot，解 region envelope；计算 `SHA256(image[0:covered_length])`。
4. 同样只比较前 20 字节。

`sha256_hash` 已确认调用 `sha256_init/update/final`；不能因比较长度为 20 字节
就把它写成 SHA-1。也不能把算法中存在 RSA / SHA-256 当作常规 RSA 签名验证
已经逐字节证实；这里应按实际 envelope 与比较循环描述。

## 已解：64 KiB 区域之前还有独立的 20 字节 trailer

主路由 `arca_validateImage` 要求非 BCM-tag 镜像长度大于 `0x10014`。
数字校验 helper 成功后，计算：

```text
S = image_length - 0x10000 - 0x14
```

| 相对 S 偏移 | 内容 |
|---|---|
| `0x00` | u32 little-endian CRC，与 `crc_getCrc32(image, S, 0xffffffff)` 比较 |
| `0x04` | 此路径未读取 |
| `0x08` | u32 little-endian chip id，与驱动返回值或兼容常量 `0x63138` 比较 |
| `0x0c` | 此路径未读取 |
| `0x10` | 此路径未读取 |

CRC helper 是无 final XOR 的反射 CRC-32；Python 等价计算是
`zlib.crc32(image[:S]) ^ 0xffffffff`。
**S 与 T 相差 20 字节；CRC/chip id 不在 T 的 `+0` / `+8`。**

随后调用 `arca_getSignature(image, S, buf, 0x40)`，并用 `strcmp` 与设备型号
字符串比较，成功返回镜像类型 2。`0x40` 是型号文本输出 buffer 的大小。
它通过 `libbcm_flashutil:getSignature → nandGetSignature` 从 NAND 镜像里的
文件系统内容找型号文本，涉及 UBI / JFFS2 解析；并非从尾部取 64 字节 RSA 签名。

## 已验证：extender 样本与主路由检查器的差异

样本 SHA-256：`ac8b23b324798f6a52465b6d6857e4fa8297fbd6c2b602d69f13537ed73514df`。

| 项目 | 值 |
|---|---|
| 文件总长 | `0xdf3000` |
| T / 64 KiB 区域起点 | `0xde3000` |
| S / 按主路由公式的 trailer 起点 | `0xde2fec` |
| T+0 / +4 / +8 | 0 / `0xde3000` / 2 |
| T+`0x28c` | `HDR0` |
| S 起的 5 个 u32 | 全部 0 |
| `crc_getCrc32(image,S,-1)` 的 Python 等价值 | `0x067077db`，与 S 中的 0 不匹配 |

`0x290` 之后仍有非零数据：相对 T 的 `0xffc0–0xffdc`、`0xfff8–0xffff`。
这两段非零 byte 后续已确认属于同一64-byte版本尾记录，见文末实际 reader / CRC 证据；不能称整个余区全零。

仅在本机内存中以主路由六个 slot 尝试对本 extender 样本的两个包装块做 RSA
解包装检查，均未得到合法的 type-2 padding；没有输出密钥或解密内容。
这只说明本次跨型号材料未匹配，不能据此宣布该样本签名有效或无效，也不能据此
推导 extender 的 rootfs 加密 key。主路由的 key slot 与extender的XZ byte变换是两个独立问题，
后者已完整解出，见[crypto路径](singtel-extender-crypto-path.md)。

旧文档把“尾部存在 64 KiB”与“必然满足主路由完整校验器”直接等同，这一步证据
不足。本样本确实符合 `HDR0` 外层布局，但没有通过以上主路由 trailer / key 检查。

## 离线检查工具

仓库的 [fwfooter.py](../fwfooter.py) 只读取本地镜像，输出 JSON：footer 位置、
covered length、key index、magic、摘要与独立的 legacy CRC 检查。
不读取 key，不解 envelope，不修改镜像；`signature_verified` 明确为 null。
退出码 0 表示成功生成检查报告，不表示固件可刷写。

```sh
python3 -I fwfooter.py /path/to/firmware.trx
```

工具已用合成布局检查 little-endian、S/T 边界、CRC 命中/失配、非法 covered length、
截断输入，并在上述真实 extender 样本核对布局。

## 未解

- 超出本篇正常原厂样本的异常输入/设备实际接受条件。
- S+4 / +0xc / +0x10 的设计含义；当前主路由校验路径没有使用它们。

## 已解状态更正

- `]Cot` 头+8已在extender真实客户端恢复并命中原厂样本：
  `zlib.crc32(image[12:declared_length]) ^ 0xffffffff`；见[精确范围和代码证据](singtel-extender-autofw.md)。
  它与本篇主路由trailer是不同校验范围。
- 原厂 extender 的两个 envelope 已完成只读离线解码与摘要核对，见文末补充；这不等同运行设备的完整升级验证链。rootfs也已独立解出，不需要flash key。
- 本样本末64-byte版本记录已解码并通过CRC核对，见文末实际reader证据。

## 证据索引

所列两个库中代码 VA 与 file offset 相同。

| 内容 | 文件 / 代码 VA | 证据 |
|---|---|---|
| 复制尾头 / magic / length / index | `libcms_util` `0x11f78` | `0x1202c–0x1203c` 复制 `0x290`；`0x12040–0x12098` 检查 |
| header envelope 与 hash 输入 | `libcms_util` `0x120dc–0x12104` | envelope 从栈内头 `+0x14c` 开始，hash 长度 `0x14c` |
| header 比较长度 | `libcms_util` `0x12110–0x12134` | word 比较，终值 `0x14` |
| region envelope 与 hash 输入 | `libcms_util` `0x12184–0x1219c` | envelope `+0x0c`；covered length 来自头 `+4` |
| region 比较长度 | `libcms_util` `0x121a4–0x121e4` | word 比较，终值 `0x14` |
| envelope 分区 / 解包装 | 无名 helper `0x11dd0` | `+0x38` 取 `0x100`；`+0x138` 取 IV；`R_OpenInit` `0x11e30` |
| RSA 与 Triple-DES 选择 | `R_OpenInit` `0x1b36c` → `0x1ad00` | `RSAPrivateDecrypt` `0x1ad24`；24 字节检查 `0x1ad44`；DES3 selector `0x1ac64` |
| SHA-256 算法 | `sha256_hash` `0x1782c` | init/update/final 三个调用 |
| S 与 T 的区分 | `arca_validateImage` `0x12be8` | S 计算 `0x12ca8–0x12cb8`；CRC `0x12cc0–0x12cd0`；chip `0x12d28` |
| 型号字符串输出与比较 | `arca_getSignature` `0x12930`；`arca_validateImage` `0x12db4–0x12dcc` | `getSignature` 调用；`strcmp`；字符串 `.rodata` `0x25882` 为主路由型号 |
| NAND 型号提取 | `libbcm_flashutil` `getSignature` `0x2b94` / `nandGetSignature` `0x6748` | 走 NAND 分支，UBI / JFFS2 解析，截取到换行 |
| 诊断原文 | `libcms_util` `.rodata` | `0x2525b` `verify firmware digital signature start.`；`0x252da` `digital signature header unenqual.` |

库 SHA-256：

- `libcms_util.so`：`480b36cfd7b169b3eb0a9a5242140f03c64accbc2d8bd815b59620c5803a8310`
- `libbcm_flashutil.so`：`657a07f6e230c53e72debacdf3b0b15ed8b834053ac85d7b274b65f711e973f5`


## 已解补充：原厂 extender 两个 envelope 离线验证（2026-11-09）

本次改用 **extender 自己的 `sbin/arc_uploadhelper`**，以已导出的 pseudocode / assembly
跟踪正常原厂样本的校验路径，再在 host 上只读复现其解码与摘要比较。没有执行固件 ELF、
修改镜像或访问设备。上述 ARM 主路由 slot 与此样本不匹配的历史结果不变；此次匹配材料
来自另一份、正确型号的 helper，不能把跨型号失败概括为“必须从 flash 取得材料”。

| 核对项目 | 结果 |
|---|---|
| 原厂样本 SHA-256 | `ac8b23b324798f6a52465b6d6857e4fa8297fbd6c2b602d69f13537ed73514df` |
| extender helper SHA-256 | `3e8c63e6ec8949adbc480f01b4af05c21e6f29ab3216d836052ec77c2d8d1814` |
| header / region 选择 | 按 helper 的正常控制流，header 固定首 slot，region 使用 footer 的 index 2 |
| 两段解码检查 | RSA type-2 padding、会话长度、CBC padding 均通过 |
| 每段解码长度 | 48 bytes：32-byte SHA-256 digest，随后16个零 |
| header 摘要范围 | footer 的前 `0x14c` bytes；完整32-byte digest 匹配 |
| region 摘要范围 | image 的前 `0xde3000` bytes；完整32-byte digest 匹配 |
| 与目标比较循环的关系 | 实现只比较前20 bytes；本次真实样本的全部32个摘要 bytes 都匹配 |

因此，这个原厂样本的两个 envelope 已经能离线解开并解释主要内容，不能再标为
“未取得匹配材料”。key 值、解码原始产物和私有验证脚本不进入公开仓库；本篇只记录结果与
可追溯的控制流。该验证没有生成可用于修改镜像的签署工具，也不意味着任何修改后的镜像
会被设备接受。现有公开 `fwfooter.py` 仍然只是结构检查工具，`signature_verified=null`
的语义不变。

**边界：** 本节仅验证两个 envelope；其后的非零记录已由下一节的独立 OWL reader 解码。
设备实际启动/升级接受条件与异常输入分支仍未穷尽。

### 本次补充的证据索引

以下均为 extender `arc_uploadhelper` 的代码 VA；RX 段对应 file offset = VA − `0x400000`。

| 符号 / 控制流 | VA | 证据 |
|---|---|---|
| `verify_firmware_signature` | `0x40201c` | 从 ]Cot 声明长度定位 footer，按 index 选择正常验证路径 |
| 两段 envelope decoder（导出名 `_ftext`） | `0x4011a0` | 调用 `R_OpenInit` / `R_OpenUpdate` / `R_OpenFinal` |
| `R_OpenInit` | `0x4031e4` | 调用 RSA 解包装并检查会话长度，再初始化对称解码 |
| 对称算法 dispatch | `0x402778` | 本路径选择 `DES3_CBCInit` |
| `R_OpenUpdate` / `R_OpenFinal` | `0x4032d0` / `0x403410` | CBC 分块和最后 padding 检查 |
| `RSAPrivateDecrypt` | `0x407454` | 检查 RSA type-2 padding 与输出长度 |
| `sha256_hash` | `0x40cd84` | SHA-256 init/update/final，算法并非 SHA-1 |
| header / region 比较循环 | `0x402508–0x40253c` / `0x4025c0–0x40260c` | 循环终值 `0x14`，仅前20 bytes |

私有复核记录为 `router-notes-private/decode-all-20261109/original-footer-verification.json`；
其中仅记录身份 hash、长度、校验布尔值与证据位置。原始样本在检查前后保持相同 SHA-256。


## 已解补充：末64-byte版本记录与余区全零填充

两个曾未解释的非零区实际上属于**同一条版本尾记录**。实际读取者不是上面的
`arc_uploadhelper`，而是 extender 的 `sbin/arc_owl_fwupgrade`：它在 envelope 验证成功后，
通过 `fseek(file, -64, SEEK_END)` 读取文件最后64 bytes，再交给 VA `0x40224c` 的 decoder。

decoder 按循环 literal 做逐 byte 条件 XOR，遇到0或与当前 literal byte相等时保留原值。
这里仅记录算法类别与调用证据，不公开 literal 值。对当前原厂样本离线解码后：

| 记录内偏移 | 大小 | 已验证内容 |
|---|---:|---|
| `+0x00` | 29 bytes | 公共型号/版本字符串 `WE410443-ST_v6.02.00_build14`，随后一个 LF |
| `+0x1d` | 27 bytes | 全零，包含文本的 NUL 结束符 |
| `+0x38` | 8 bytes | ASCII 十六进制 CRC；实现用 `%x` 解析 |

实现对**解码后的前56 bytes**计算 raw reflected CRC-32，初始 state为 `0xffffffff`，
与最后8字符解析结果比较。host 等价核对 `zlib.crc32(decoded[:56]) ^ 0xffffffff`
与样本记录一致；型号、版本、build号也与公开固件文件名完全一致。这是代码读取路径与
原始样本校验的联合证据，不是靠 printable 字符猜字段。

完整64 KiB footer现可按以下区间区分（T=`0xde3000`，右端不包含）：

| 区间 | 文件偏移 | 内容与状态 |
|---|---|---|
| `T+[0,0x290)` | `[0xde3000,0xde3290)` | HDR0结构与两个已离线验证的 envelope；保留字段的设计语义仍不猜测 |
| `T+[0x290,0xffc0)` | `[0xde3290,0xdf2fc0)` | **64,816 bytes 全零填充**，逐 byte 验证 |
| `T+[0xffc0,0x10000)` | `[0xdf2fc0,0xdf3000)` | 64-byte条件XOR版本记录，已解码并通过其CRC |

这里没有把 padding 当成加密。所有已观察到的 footer 非零区域已有结构或解码对应；
这不等于解释了每个保留字段的设计用途，也不构成可刷写自定义镜像的验证。

### 版本尾记录证据索引

`arc_owl_fwupgrade` SHA-256：
`b97cf9fe005ae38263b1a80f9453071b86a91123bc6ec03e7ee9b95d9553a5a1`。
下表代码 VA 与 file offset 相差 `0x400000`。

| 内容 | VA | 证据 |
|---|---|---|
| seek到末64 bytes | `0x403c30–0x403c40` | offset=-0x40、whence=2，调用 `fseek` |
| 读64 bytes | `0x403c60–0x403c74` | `safe_fread(buffer,1,0x40,file)` |
| decoder调用 | `0x403c84` | 调用 `0x40224c`，长度0x40 |
| 条件XOR | `0x402374–0x402394` | zero/equality分支及 `xor` / `sb`；考虑MIPS delay slot |
| 取CRC文本 | `0x403cb0–0x403cec` | 取记录+0x38起8 bytes，并跳过前导零 |
| hex解析 | `0x403d00–0x403d14` | `sscanf` 的 `%x` 字符串在VA `0x411878` / file `0x11878` |
| CRC计算 | `0x403d1c–0x403d30` | 调用 `crc32` VA `0x406478`，长度0x38、初始state=-1 |
| CRC比较 | `0x403d94–0x403d9c` | 比较计算值与解析值，相等才走成功分支 |

私有 `footer-version-tail-verification.json` 记录样本hash、reader hash、匹配结果与地址；
解码原始记录仅保留在私有目录。没有修改样本或执行目标程序。
