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
