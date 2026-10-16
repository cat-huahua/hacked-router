# NETGEAR 配置备份解密（.cfg）

2026-10-16 实测，在 **R7800** 上验证。**结论：完全可解，而且不需要任何设备信息 —— 种子就写在文件头里。**

## 文件格式

```
偏移 0   magic  4 字节   ← ★ 这就是 srand() 的种子，例如 0x20131224
偏移 4   len    4 字节   加密数据的长度（小端）
偏移 8   crc    4 字节   累加校验（不是 CRC32，名字骗人）
偏移 12  密文   len 字节
```

`headerSize = 12`，按 **4 字节一块** 处理。

## 加密算法（**不是 AES**）

```c
srand(magic);                       // ★ 种子 = 文件头里的 magic
for (i = 0; i < len; i += 4)
    out[i..i+4] = in[i..i+4] ^ rand();     // 4 字节一块 XOR
```

校验：

```c
crc = header.crc;
for (i = 0; i < len; i += 4) crc += LE32(pt[i..i+4]);
assert(crc == 0xffffffff);
```

**两种 libc 的 `rand()` 都可能**（设备固件用哪个决定）：

- **uClibc**：`TYPE_3` 随机数发生器（`randtbl` 31 项 + Lehmer LCG `16807*lo - 2836*hi`），播种后空转 `31*10` 次
- **musl**：LCG `state = 6364136223846793005*state + 1`，取 `state >> 33`

**两个都试，哪个校验通过就是对的。**

## 为什么这么容易解

**种子在文件里。** 对比华为：华为的密钥在设备上（`/etc/wap/aes_string`），
NETGEAR 把种子直接写进了文件头 —— 等于**把钥匙插在锁上**。

这也解释了另一个观察：**同一台设备不同时期的备份，从偏移 12 起密文逐字节相同**
（没有随机 IV，确定性 keystream，相同明文 → 相同密文）。

## 解密出来能看到什么（R7800 实测）

```
http_username       = admin
http_passwd         = <SHA256>             ← 管理密码的 SHA256
wla_ssid / wl_ssid  = <2.4G/5G 的 SSID>
wla_wpa2_psk        = <★ WiFi 密码明文！>
wla_channel         = <5G 信道>
wl_channel          = <2.4G 信道>
lan_factory_mac / cur_wanmac / wan_factory_mac
dhx2_passwd         = $1$...              ← MD5-crypt
samba_passwd        = <MD5>
PWD_answer1/2       = <SHA256>            ← 安全问题答案
PWD_question1/2     = <问题编号>
wan_pppoe_username
```

**格式是 `key=value`，记录之间用 `\x00` 分隔**（约 1200 条）。

## 怎么验证解对了（重要）

**不要靠"看起来像明文"判断。** 用已知值交叉验证：

```python
hashlib.sha256("已知的管理密码".encode()).hexdigest() == cfg["http_passwd"]   # ✓
"已知的 WiFi 密码" in 解密结果                                              # ✓
```

**两个方向同时成立才算钉死。**

## 怎么用

```bash
python3 netgear_r7800/ng_cfgdec.py 备份.cfg
# → 生成 备份.cfg.dec.uclibc（或 .dec.musl）
```

配置从路由器网页导出即可（**高级 → 管理 → 备份设置**）。

## ★ 口令字段分别用什么哈希（哈希模式对照表）

**解出明文之后最容易踩的坑**：这些口令字段**不是同一种哈希**。拿 MD5 去跑
`samba_passwd` 永远不出结果。

| 配置字段 | 算法 | hashcat 模式 |
|---|---|---|
| `http_passwd` / `http_passwd_digest` | **裸 SHA256(明文)**，无盐 | `-m 1400` |
| `dhx2_passwd` | **MD5-crypt**（`$1$` + 盐 + `$`） | `-m 500` |
| `samba_passwd` | **NTLM = MD4(UTF-16LE(明文))** | `-m 1000` |
| `PWD_answer1` / `PWD_answer2` | **裸 SHA256(答案)** | `-m 1400` |
| `wl_wpa2_psk` / `wla_wpa2_psk` | **明文**（不用破） | — |

### 两个反直觉点

1. **`samba_passwd` 不是 MD5。** NETGEAR 的 ReadySHARE 走 Samba，存的是 **NTLM**
   哈希 —— 也就是把明文按 **UTF-16LE** 编码后再算 MD4。
   注意：**`-m 900`（raw MD4 of ASCII）也不对**，编码必须是 UTF-16LE，否则差之毫厘。
2. **`PWD_answer*` 跟管理密码不是同一套。** 实测里 `http_passwd` / `dhx2_passwd` /
   `samba_passwd` 三个字段解出来是**同一个口令**（这家把管理密码、HTTP digest、
   Samba 共用一套），但两个**安全问题答案**用同一批候选（49 万条家庭相关的
   大小写 / leet / 数字后缀 / 拼接变体）**全部未命中** —— 是另外两个字符串。

### ⚠️ 验证多模式时 `--show` 会串味

hashcat 的 potfile 只存 `hash:明文`，**不记录模式**。所以同一个
`--potfile-path` 先跑 `-m 1000` 命中之后，再跑 `-m 900 ... --show`，
会**把 mode 1000 的条目当成自己的结果**打印出来 —— 看起来像"MD4 也命中了"。

**验证不同模式必须各用各的 `--potfile-path`。** 我就是这样差点误报了一次。

### 怎么生成定向字典（比硬啃 rockyou 高效得多）

比起直接上大字典，**先从已经解出来的配置里"反推"口令习惯**更划算。
同一户人家在不同设备/不同年代的口令通常同源，可用的种子：

```
SSID 里的名字（如 "HomeSweetHome" 里的 Home/Sweet）· 家庭成员名（大小写/全拼/缩写）
设备默认的 psk（旧备份里的 wl_wpa2_psk）· wl_ssid_password 之类的数字串
```

再对每个种子派生：**首字母大写 / 全大写 / 全小写**、**数字后缀 0-9999**、
**符号后缀**（`!` `@` `1` `123` `!@#`）、**leet 替换**（`a→4` `o→0` `e→3` `s→5`）、
**名字之间的排列组合**。这样几十万条候选就能覆盖大部分家用口令，
**几十秒跑完**，比 rockyou 快得多。

## 注意

- **不同型号/不同设备族的 magic 可能不同**（同一个 12 字节头结构，magic 不一样）。
  实测：一台设备的三份备份 magic 都是 `0x20131224`；另一台（名字带 Switcher）也是同一个 magic
  但校验不过 —— 说明**同 magic 也可能对应不同设备族的密钥流**，两个 RNG 都要试。
- 参考实现：[`fysac/orbicfg`](https://github.com/fysac/orbicfg)（Go，为 Orbi 写的，但算法是通用的）。
  它源码里还有一张「宣称的 magic ≠ 实际 magic」的覆盖表 —— 有些设备头里写的值是错的。
- 路由器上负责这件事的二进制是 `/bin/datalib`。

---

# ★ 附：官方固件分析（2026-10-16）

**结论：官方固件的 rootfs 完全可解，而且二进制层面证实了本文的加密分析。**

## 固件直链与容器结构

```
https://www.downloads.netgear.com/files/GDC/R7800/R7800-V1.0.2.90.zip   (30 MB)
```

解开 zip 得到一个 `.img`，结构是：

```
偏移 0x0       文本头（明文）
               device:R7800 / version:V1.0.2.90 / region: /
               hd_id:29764958+0+128+512+4x4+4x4+cascade
偏移 0x80      uImage（"Linux-3.4.103" 内核）
偏移 0x220040  第二个 uImage
偏移 0x220080  ★ squashfs 超块（合法、明文）
               inodes=3862  block=262144  comp=4(xz)  flags=0x06c0
偏移 0x666CFD  "CHK" 标记
```

切出 0x220080 之后的部分直接 `unsquashfs -d sq rootfs.sqsh` ——
**成功解出 3245 个文件 / 161 目录 / 456 符号链接**。

## ★ 二进制层面证实了配置加密分析

`/bin/datalib`（负责读写配置的那个二进制，40 KB，ARM ELF，stripped）：

```
$ file bin/datalib
ELF 32-bit LSB executable, ARM, EABI5, dynamically linked,
  interpreter /lib/ld-uClibc.so.0, stripped

$ readelf -sW bin/datalib | grep -E 'srand|rand'
   UND rand        ← ★
   UND srand       ← ★

$ ls -la lib/ld-uClibc*
  ld-uClibc-0.9.33.2.so     ← ★ 就是 uClibc 0.9.33.2
```

**三条独立吻合**：
1. `datalib` 导入 `srand` / `rand` → 印证"用 rand() 生成密钥流"；
2. 链接的是 **uClibc 0.9.33.2** → 印证"要用 uClibc 那一支的 `rand()`（TYPE_3）"，
   这也解释了为什么我们的配置是用 `uclibc` 而不是 `musl` 解开的；
3. `datalib` 里有 `http_passwd` / `samba_passwd` / `wl_wpa2_psk` / `wla_wpa2_psk` 等
   字段名，以及 `/tmp/datalib-bakrst.bin`（备份恢复用的临时文件，正是我们解的那种格式）。

**所以本文开头那套算法不是猜的，是从固件二进制里核对过的。**

## ⚠️ 一个判据上的教训（值得单列）

`unsquashfs` 读这份**健康的** NETGEAR 镜像时会报：

```
xz: error reading stored compressor options from filesystem!
```

**但它照样把 3245 个文件全解出来了。** 所以这条信息**只是无害警告**，
**不能作为"文件系统坏了/被加密了"的依据**。

我早先在分析另一台设备（Singtel extender）的加密 rootfs 时，
**把这条当成了加密的证据之一** —— 是错的，已在
[arcadyan-singtel-config-format.md](arcadyan-singtel-config-format.md) 里更正。

> **判据必须能区分"良性"和"恶性"**，不能只看到一句 error 就下结论。
> 那次真正的硬证据是 `xz uncompress failed with error code 7` +
> `FATAL ERROR: File system corruption detected`（数据块真的解不开），
> 以及"数据区 0 个 XZ 魔数"（对照：这份 NETGEAR 健康镜像有 434 个）。

## ★ 一个很有说服力的对比：同一台设备上「有真加密」和「没加密」

同一个 rootfs 里还有一个 NETGEAR 自家的加密库 `lib/libntgrcrypt.so`（24 KB）：

```
导出的函数：
  ntgrcrypt_sec_part_open / _close / _reset          ← "安全分区"
  run_cmd_cryptsetup_luksformat / luksopen / luksclose / luksstatus
                                                     ← ★ cryptsetup LUKS（真·全盘加密）
  run_cmd_openssl_aes_dec                            ← 走 openssl 的 AES 解密
  interleave_file                                    ← 还有一步交错/混淆
  ntgrcrypt_key_init / ntgrcrypt_key_get_file / key_rm_file
  ntgrcrypt_get_count / add_count / _count_change    ← 变更计数器
```

**也就是说：这台设备上 NETGEAR 有能力用 LUKS + AES + 计数器做真加密 ——
但配置备份偏偏只用 `rand()` XOR。**

这不是"厂商不会加密"，而是**权衡的结果**：配置备份要能被设备自己、
被 TFTP 恢复、被售后工具在资源极少的早期启动阶段读写，
所以选了最轻的方案 —— **代价就是把种子直接写在文件头里**。

**结论没变，但更清楚了**：本文开头那套算法是**设计选择**，不是疏漏的巧合。
反过来说，同一台设备上其他地方（安全分区）用的是 LUKS ——
**所以"某台 NETGEAR 的备份能解"不等于"这台设备的其他东西也能解"**，
要分清楚分析的是哪一层。

---

# ★ 附：`PWD_question1/2` 的编号对应哪两个问题

解密出来的配置里，安全问题只存**编号**（如 `PWD_question1=4`），看编号根本不知道问的是什么。
从官方固件的语言文件里可以拿到完整对照表
（`www/languages-en.js` 与 `www/language/English.js`）：

```
PWD_question1（第一个安全问题的槽位，共 9 个选项）
  1  What was the name of the first NETGEAR product you purchased?
  2  What was the name of the first school you attended?
  3  What is your oldest sister's first name?
  4  What is your oldest brother's first name?
  5  In what city were you born?
  6  What is your grandmother's first name?
  7  What is your grandfather's first name?
  8  In what year (YYYY) did you graduate from high school?
  9  What is the name of your first employer?

PWD_question2（第二个槽位，共 8 个选项）
  1  What is your youngest sister's first name?
  2  What is your youngest brother's first name?
  3  What is your father's middle name?
  4  What is your mother's middle name?
  5  What was the first name of your first manager?
  6  In what city was your mother born?
  7  In what city was your father born?
  8  What is your best friend's first name?
```

**注意两个槽位的选项列表是不同的**（一个 9 项、一个 8 项），
所以 `PWD_question1` 和 `PWD_question2` 的同一个数字代表**不同的问题**。

配套的 CGI 是 `www/securityquestions.cgi`（里面用 `quest1_1..quest1_9` /
`quest2_1..quest2_8` 这些语言变量填充下拉框）。

这样解出来的配置才算**完整**：字段名 → 值 → **值是什么含义**。
