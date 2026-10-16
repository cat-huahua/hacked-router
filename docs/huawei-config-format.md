# 华为路由器配置备份的格式（`aescrypt2`）

2026-10-16 分析。**结论：格式完全破译，但密钥在设备上、不在文件里 —— 光靠备份文件解不开。**

## 文件格式

```
偏移 0    32 字节   明文头（八个大端 uint32；同一设备的不同备份【完全相同】）
偏移 0x20 16 字节   IV
偏移 0x30 ...       AES-256 密文
```

实测头值：`2, 0x70, 1, 1, 0x42, 5, 2, 1`

**注意**：`aescrypt2` 自己生成的文件只有 `[16字节 IV][密文]`。
设备那边在前面又加了 32 字节，所以从文件里解要先把头去掉。

## 算法（来自 `palmerc/AESCrypt2` 源码）

**加密时**：

```c
// 1. IV 由时间去派生（所以每次备份的 IV 都不同）
sha256(cur_time(8, LE) || filesize(8, LE) || input_filename) → IV[0..16]
IV[15] = (IV[15] & 0xF0) | (filesize & 0x0F);   // 末字节低 4 位塞文件长度
write(IV);                                       // 16 字节 IV 写在最前面

// 2. 迭代 8192 次把 IV 和密钥串揉起来当 AES 密钥
digest = IV;
for (i = 0; i < 8192; i++)
    digest = sha256(digest || user_key);
aes_set_key(aes_ctx, digest, 256);               // AES-256

// 3. 逐块加密（每块先 XOR IV，再 AES —— 注意不是链式 CBC）
for (offset = 0; offset < filesize; offset += 16) {
    buffer[0..16] ^= IV;
    aes_encrypt(aes_ctx, buffer);
    write(buffer);
}
```

**`user_key` 是密钥文件的原始内容**（含 `hex:` 前缀）。

## 密钥在哪

**不在备份文件里。** 在设备的 `/etc/wap/aes_string`。
- 老的光猫（HG 系列）全网共用一把：`hex:13395537D2730554A176799F6D56A239`
- **消费级路由器（如 Q2S / WS5281）不是这把** —— 实测全偏移扫描（0~96，步长 4）
  × 两种密钥写法（带/不带 `hex:`）全部失败

**要拿到设备那把，只能有 shell 或者设备固件。**

## 密码在解密后的配置里长什么样

```
http_passwd      → SHA256(MD5(明文))
```
也就是**两层哈希**。hashcat 能跑，但不是常见模式，要先自己拼。

## 怎么用

```bash
# 从源码自己编译（别跑仓库里那个预编译二进制）
git clone https://github.com/palmerc/AESCrypt2 && cd AESCrypt2
cc -O2 -o aescrypt2 aescrypt2.c aes.c sha256.c -D_FILE_OFFSET_BITS=64

printf 'hex:那把密钥' > key.txt
dd if=备份.conf of=no_hdr bs=1 skip=32      # 去掉设备加的 32 字节头
./aescrypt2 1 no_hdr out.gz key.txt          # 1 = 解密
gunzip out.gz                                # → 明文 XML
```

## 参考

- [`palmerc/AESCrypt2`](https://github.com/palmerc/AESCrypt2) —— 逆向出来的 C 实现
- [`Jakiboy/Ratr`](https://github.com/Jakiboy/Ratr) —— GUI 版（Huawei + ZTE）
- 老固件用固定密钥；**R022+ 改成「一机一密」**（AES-256-GCM，密钥在 `/mnt/jffs2/kmc_store_A`），
  而且加了 HMAC-SHA256 校验文件，改过的配置不重新签名不生效
