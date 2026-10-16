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

## 注意

- **不同型号/不同设备族的 magic 可能不同**（同一个 12 字节头结构，magic 不一样）。
  实测：一台设备的三份备份 magic 都是 `0x20131224`；另一台（名字带 Switcher）也是同一个 magic
  但校验不过 —— 说明**同 magic 也可能对应不同设备族的密钥流**，两个 RNG 都要试。
- 参考实现：[`fysac/orbicfg`](https://github.com/fysac/orbicfg)（Go，为 Orbi 写的，但算法是通用的）。
  它源码里还有一张「宣称的 magic ≠ 实际 magic」的覆盖表 —— 有些设备头里写的值是错的。
- 路由器上负责这件事的二进制是 `/bin/datalib`。
