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
| `0x290–0xffff` | 剩余部分 | 本 helper 不读取；不能一律命名为 padding |

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
这些字段暂不命名，不能称整个余区全零。

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

- extender 本身的匹配 key slot、真实校验器行为与尾区剩余字段。
- S+4 / +0xc / +0x10 的设计含义；当前主路由校验路径没有使用它们。
- `]Cot` 头+8已在extender真实客户端恢复并命中原厂样本：
  `zlib.crc32(image[12:declared_length]) ^ 0xffffffff`；见[精确范围和代码证据](singtel-extender-autofw.md)。
  它与本篇主路由trailer是不同校验范围。
- 没有完成 extender envelope 的解密验证；rootfs已独立解出，不需要flash key。

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
