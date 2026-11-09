# WE410443-ST：kernel 内嵌的 MT7615 MCU firmware

## 已解：三个不属于 rootfs ELF 的映像

2026-11-09 静态检查在解压后的 kernel 中找到三个 Wi-Fi MCU byte arrays。
其中两个 RAM firmware 映像确实仍以加密下载格式保存；另一个 ROM patch 的加载路径没有启用解密。
这与 [extender rootfs 已完整解码](singtel-extender-crypto-path.md) 是不同层次。
“所有已识别 ELF 完成批量导出”不能改写成“所有内嵌 code 均已反编译”。

输入 kernel：7,743,232 bytes，SHA-256
`9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a`。
映射规则：`VA = file offset + 0x81001000`。以下长度同时由 kallsyms 地址与
driver 消费端立即数核对；没有把“到下个符号的距离”直接当成数组长度。

| 内嵌符号 | VA | kernel file offset | 精确长度 |
|---|---:|---:|---:|
| `mt7615_rom_patch` | `0x8169abb0` | `0x699bb0` | `0x2b5e` / 11,102 |
| `MT7615_CR4_FirmwareImage` | `0x8169d710` | `0x69c710` | `0x1cb14` / 117,524 |
| `MT7615_FirmwareImage` | `0x816ba224` | `0x6b9224` | `0x70e08` / 462,344 |

ROM patch 到下一符号的跨度是 11,104 bytes；提取只取 driver 指定的 11,102 bytes。
三个原始 blob、分出的 download regions 与分析清单均留在仓库外私有目录。

## 已解：RAM firmware 的 region 与 encryption flags

Linux 官方 mt76 driver 给出 packed `mt7615_fw_trailer`：每个 region 的尾记录
为 36 bytes，记录 load address、chip/feature/eco、版本/日期和 region length；
下载长度为记录的 length 加四字节 CRC。N9 有两个 region，CR4 有一个。
本样本的长度计算均精确覆盖整个 blob，无剩余无法归属的尾数据。
参见 [Linux v6.12 mt7615/mcu.c](https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/net/wireless/mediatek/mt76/mt7615/mcu.c)。

下表 offset 均相对于各自 blob，不是 kernel 文件：

| 映像 / region | payload offset | 记录长度 | 下载长度（含 CRC） | trailer offset | load address | feature |
|---|---:|---:|---:|---:|---:|---:|
| N9 / 0 | `0x0` | 409,596 | 409,600 | `0x70dc0` | `0x00084000` | `0x01` |
| N9 / 1 | `0x64000` | 52,668 | 52,672 | `0x70de4` | `0x0209c400` | `0x01` |
| CR4 / 0 | `0x0` | 117,484 | 117,488 | `0x1caf0` | `0x90000000` | `0x01` |

官方定义 `FW_FEATURE_SET_ENCRYPT` 为 bit 0，key-index 为 bits 2:1；
下载 mode 另有 reset-IV、CR4 与 need-response 位。因此本样本三个 region 的
ENCRYPT 均置位、key-index 均为 0。该 index 不是 key 内容。
参见 [Linux v6.12 mt76_connac_mcu.h](https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/net/wireless/mediatek/mt76/mt76_connac_mcu.h)
及 [mode 生成实现](https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/net/wireless/mediatek/mt76/mt76_connac_mcu.c)。

这不只是套用另一版 driver 的结构或根据 entropy 猜测：本 kernel 的
`AndesMTLoadFw` 也读取相同尾记录，把 `feature & 7` 放进下载 mode，bit 0
置位时再加 `8`，随后将原始 region bytes 交给 `MtCmdFwScatters`。
对本样本计算得到 N9 mode=`0x80000009`、CR4 mode=`0x80000019`。
这是**静态加载链证据**；本轮没有执行 MCU 下载或观察设备解密。

N9 路径以 `MtCmdFwStartReq(adapter, 1, first_region_address)` 启动，故本样本
请求的 override entry 是 `0x84000`。CR4 使用 `(adapter, 4, 0)`：0 是命令参数，
不能把它当成已经验证的实际 entry；具体 entry 由 MCU/ROM 启动机制决定。
同样，`0x90000000` 是 CR4 download base，不自动等同 entry。

## 已解：ROM patch 的外层结构和下载范围

ROM patch 使用 30-byte header，随后 11,072-byte payload。外层包含构建日期、
platform、hardware/software version、patch version 与 checksum；格式与上述
官方 `mt7615_patch_hdr` 相符。checksum 本轮仅解析，尚未独立验证其计算结果。

本 kernel 的 `AndesMTLoadRomMethodFwDlRing` 用 `size - 0x1e` 计算长度，
从 blob `+0x1e` 下载到配置地址 `0x80000`，mode=`0x80000000`，没有 ENCRYPT 位；
随后发送 `MtCmdPatchFinishReq`。因此这条路径把 patch 当作无需下载解密的明文
patch payload。payload 仍可能包含 patch tables、代码和数据，不能全部当成指令。
`0x80000` 只是下载地址；这里没有独立的直接 entry 参数。

## 未解：密钥、ISA 与完整 MCU 语义

- 两个 RAM firmware 尚未解密。匹配 key 当前缺失；本轮没有确定其保存位置、
  获取方式或完整密码算法，不能把 key-index=0 当成已得到 key，也不猜测它必在某个 flash 分区。
- CR4 的角色由原厂符号及对应下载 mode 确认。模块厂商资料确认 MT7615 含
  ARM Cortex-R4；将此 CR4 blob 对应到该核心有硬件资料与 driver 命名支持，
  但尚未验证本样本解密后指令和启动状态。
  参见 [AsiaRF AW7615-NP1 datasheet](https://asiarf.com/wp-content/uploads/2023/08/AW7615-NP1_V1-P1-conpressed.pdf)。
- N9 和 ROM patch 的精确 ISA/entry layout 尚未由本样本确认。名称 `N9` 或
  driver 前缀 `Andes` 本身不足以完成 ISA 识别。有限的 architecture 字符串检索也未给出确认信息。
- 本机 `rasm2 -L` 列出 `nds32` / `AndesTar v3 NDS32 (binutils)`，Ghidra 安装含 ARM
  processor；这些是工具能力，不是本样本 ISA 的证据。本轮没有强行按 ARM/MIPS/NDS32
  对未知或加密 bytes 生成所谓“已完成反编译”的结果。
- 搜索覆盖 verified kernel kallsyms，以及 rootfs 258 个 ELF 文件的 251 个不同内容
  （符号表读取无错误）。名称匹配得到 34 条 rootfs ELF 符号，没有发现名称匹配且
  同时具备正 size 与 file mapping 的 OBJECT/NOTYPE 数组。这是限定命名规则的搜索结果，
  不排除 stripped、匿名或其他命名的内嵌 code。

## 证据索引

| 符号 / 位置 | VA / file offset | 静态证据 |
|---|---|---|
| `mt7615_fw_prepare` | `0x8131cc98` / `0x31bc98` | ROM patch 与 N9 array 指针/长度 |
| patch 指针/长度赋值 | `0x8131cce0–0x8131ccf0` / `0x31bce0–0x31bcf0` | `0x8169abb0` 与 `0x2b5e` |
| N9 指针/长度赋值 | `0x8131ccf4–0x8131cd18` / `0x31bcf4–0x31bd18` | `0x816ba224` 与 `0x70e08` |
| `mt7615_init` 中 CR4 赋值 | `0x81320fb4–0x81320fc8` / `0x31ffb4–0x31ffc8` | `0x8169d710` 与 `0x1cb14` |
| patch address 初始化 | `0x81320ffc`, `0x81321020–0x81321024` / `0x31fffc`, `0x320020–0x320024` | `lui t1,0x8`，保存 `0x80000` |
| `fw_info` | `0x8134f620` / `0x34e620` | 尾记录地址、feature 与 length+4 解析 |
| N9 feature → mode | `0x8135077c–0x8135079c`, `0x81350d60–0x81350d80` | bit 0、low 3 bits、reset-IV 与 address/length request |
| N9 start | `0x81350f5c–0x81350f68` / `0x34ff5c–0x34ff68` | 第一个 region address，start flag=1 |
| CR4 mode / scatter / start | `0x81351068–0x81351088`, `0x813510ec`, `0x8135118c–0x81351198` | CR4 bit、原 region bytes、start flag=4/address=0 |
| patch request / scatter / finish | `0x81351bc4–0x81351c04` / `0x350bc4–0x350c04` | mode=`0x80000000`、blob+30、patch finish |

提取结果 SHA-256：

| blob | SHA-256 |
|---|---|
| ROM patch | `bc13aac3d139f4554d51b25799f1f2fbb00aaae102d2ae3a7687d344d94abd08` |
| CR4 | `14735104a426a9060b5d781fc691ab27c67c6e5cf650edf79ddf1fc078f5a666` |
| N9 | `613b58d57bc9e5aff16ee92476d6a3eac157e2eb1b9eda13cc966437068e0332` |

私有 `decode-all-20261109/embedded-code/manifest.json` 与 `regions.json` 保留完整
提取、region、输入 hash、参考 source URL 与状态记录。没有上传 blob、设备凭据或 key。
