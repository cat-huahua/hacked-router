# 华为路由器配置备份的格式（`aescrypt2`）

2026-10-16 从 [palmerc/AESCrypt2 源码](https://github.com/palmerc/AESCrypt2) 逐行核实后**重写**。
**结论：格式完全破译；密钥在设备上、不在文件里 —— 光靠备份文件解不开。**

> ⚠️ **本文档在 2026-10-16 做过一次重要更正。** 早先版本把两处写错了
> （密钥派生首轮输入、以及分组模式），导致"用通用密钥解不开"被误判成"密钥不对"。
> 更正后重新验证：**通用密钥在正确算法下依然解不开消费级机型** —— 结论没变，
> 但依据从"猜"变成了"实锤"。

## 文件格式

```
偏移 0    32 字节   设备加的明文头（8 个大端 uint32；同一设备的不同备份【完全相同】）
偏移 32   16 字节   IV
偏移 48   N 字节    AES-256 密文（CBC 链式，见下）
偏移 末尾 32 字节   HMAC-SHA256 校验（★ 早先版本漏了这一项）
```

实测头值：`2, 0x70, 1, 1, 0x42, 5, 2, 1`

**注意**：`aescrypt2` 自己生成的文件只有 `[16字节 IV][密文][32字节 HMAC]`。
设备在**前面又加了 32 字节**，所以从文件里解要先把头去掉、把尾巴切掉。

## 算法（★ 与早先版本不同的地方已标注）

### 1. IV

`aescrypt2` 加密时由时间去派生 IV（所以每次备份的 IV 都不同）：

```c
sha256(cur_time(8, LE) || filesize(8, LE) || input_filename) → IV[0..16]
IV[15] = (IV[15] & 0xF0) | (filesize & 0x0F);   // 末字节低 4 位存【最后一块的有效字节数】
write(IV);                                       // 16 字节 IV 写在密文最前面
```

解密时 `lastn = IV[15] & 0x0F` 用来把最后一块截回真实长度。

### 2. 密钥派生 ★★ 容易写错的地方

```c
memset(digest, 0, 32);
memcpy(digest, IV, 16);        // ★★ digest 是 32 字节：IV 后面【补 16 个零字节】
for (i = 0; i < 8192; i++) {
    digest = sha256(digest /*整个 32 字节*/ || user_key);
}
aes_set_key(aes_ctx, digest, 256);   // 32 字节直接当 AES-256 密钥
```

**早先版本写成了 `digest = IV`（只有 16 字节）** —— 首轮输入少了一半，
派生出来的密钥完全不同，**这就是"通用密钥解不开"的真正原因之一**。

### 3. 分组模式 ★★ 也写错了

**是 CBC 链式**，不是"每块独立 XOR IV 再 AES"：

```c
/* 加密 */
for (每 16 字节块) {
    buffer[0..16] ^= IV;
    aes_encrypt(aes_ctx, buffer);
    memcpy(IV, buffer, 16);        // ★ IV 更新为【刚产生的密文块】→ 这就是 CBC
    write(buffer);
}
/* 解密 */
for (每 16 字节块) {
    memcpy(tmp, buffer, 16);
    aes_decrypt(aes_ctx, buffer);
    buffer[0..16] ^= IV;
    memcpy(IV, tmp, 16);           // ★ 同样链式
    write(n 字节);                  // 最后一块只写 lastn 字节
}
```

### 4. HMAC-SHA256 尾巴

密文后面跟 32 字节 HMAC-SHA256（ipad 64×0x36 / opad 64×0x5C，
前 32 字节分别与派生出的 digest 异或，内层哈希吃整段密文）。

> **★ 这个尾巴是验证密钥的最好工具。** 256 位判据，零误判 ——
> 比"看解密出来像不像明文"可靠得多。试密钥时**先验 HMAC**。
> 本仓库的 `routercfg.py --test-key` 就是干这个的。

## 密钥在哪：`/etc/wap/aes_string`

**不在备份文件里。**

| 机型 | 密钥串 | 状态 |
|---|---|---|
| 老的 `HG` 系列光猫 | `hex:13395537D2730554A176799F6D56A239` | **全网共用**，社区公开 |
| **消费级（Q2S / WS5281 等）** | 未知 | ★ **实测不是上面那把** |

**怎么确认"不是那把"的**（2026-10-16）：用更正后的算法，
对 5 份备份 × 头部偏移 0~96 × 尾长 {0,32} × 3 种密钥写法（带/不带 `hex:`、大小写），
**HMAC 判据全部失败**。所以它不是。

消费级机型的密钥是**一机一密**，在设备的 `/etc/wap/aes_string`。
拿到它的途径只有三条：设备 shell、设备固件、或厂商泄漏 —— **备份文件本身给不出来**。

## 密码在解密后的配置里长什么样

```
http_passwd  →  SHA256(MD5(明文))     ← 两层哈希
```

## 怎么用

```bash
# 从源码自己编译（别跑仓库里那个预编译二进制）
git clone https://github.com/palmerc/AESCrypt2 && cd AESCrypt2
cc -O2 -o aescrypt2 aescrypt2.c aes.c sha256.c -D_FILE_OFFSET_BITS=64

printf 'hex:那把密钥' > key.txt
dd if=备份.conf of=no_hdr bs=1 skip=32        # 去掉设备加的 32 字节头
head -c -32 no_hdr > no_tail                   # 去掉 32 字节 HMAC
./aescrypt2 1 no_tail out.gz key.txt           # 1 = 解密
gunzip out.gz                                  # → 明文 XML
```

## 仓库里的工具：`hwkey.c`（高速密钥破解/验证器）

Python 跑这条链太慢（一条候选 5ms 以上）。`hwkey.c` 利用一个关键优化 ——
**每轮迭代的输入长度固定**（32 + key 长度），填充可以预计算一次，
之后每轮只需**一次 SHA256 压缩**：

```bash
cc -O3 -march=native -pthread -o hwkey hwkey.c -lcrypto

./hwkey 备份.conf derive <密钥串>          # 打印派生密钥（交叉验证用）
./hwkey 备份.conf verify <密钥串>          # ★ 用 HMAC 判据验一把密钥
./hwkey 备份.conf dict   <词表> [前缀]      # 字典（前缀常用 hex:）
./hwkey 备份.conf mask   '?l?l?l?l?l?l' [前缀]
```

实测速度 ≈ 2400 条/秒（8 线程，i7-1185G7）。

> **★ 写这类工具一定要做交叉验证。** 我这个实现里连踩两个坑：
> ① 覆盖 IV 时按 32 字节循环，而 IV 只有 16 字节 → **越界读取**，
> 把本该是零的字节写成了垃圾；
> ② 把上一轮的 digest 留在 `st` 里当**下一轮 SHA256 的初始状态**了 ——
> 而 `st` 是哈希初值不是消息，正确的做法是**每轮都从标准初值重新开始**。
>
> 两个坑都会让结果"看起来能跑但全错"。**要不是拿 Python 实现逐用例对比
> （5/5 一致才算过），我会用错实现跑一整夜，然后得出一个假的"没找到"。**

## 参考

- [`palmerc/AESCrypt2`](https://github.com/palmerc/AESCrypt2) —— 逆向出来的 C 实现（**本文档以它为准**）
- [`Jakiboy/Ratr`](https://github.com/Jakiboy/Ratr) —— GUI 版（Huawei + ZTE）
- 老固件用固定密钥；**R022+ 改成「一机一密」**（AES-256-GCM，密钥在 `/mnt/jffs2/kmc_store_A`），
  而且加了 HMAC-SHA256 校验文件，改过的配置不重新签名不生效
