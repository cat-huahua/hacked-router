# EmbedUR 云代理的固件镜像格式（`image_manager`）

> 设备：Singtel Mesh Router（Arcadyan WG9116AEAC23-ST）
> 材料：`/usr/bin/embedur/erm_agent.tar.bz2` 里的 `image_manager`（879 KB）
> 方法：静态反汇编（ARM，OpenSSL 1.0.1j 静态链接）
> **结论：这是与 `fw_upgrade` 完全不同的第二条升级链。**

---

## 1. 调用方式

`main`（`0x13878`）第一句就是：

```c
if (argc != 6) {
    fputs("Invalid number of arguments.\n", stderr);
    return -1;
}
```

即 `image_manager` 需要 **6 个参数**（argv[0] + 5 个）。从后续寄存器用法看：

| 参数 | 用途（从 `main` 的寄存器用法确认） |
|---|---|
| `argv[1]` | 输入镜像文件（`r6`） |
| `argv[2]` | 第二个输入文件（`fcn_1410C` 的 `arg2`，很可能是证书/签名文件） |
| `argv[3]` | key 文件（`fcn_13C44` 的 `arg2`，`fseek` 到 0x6C 读密钥） |
| `argv[4]` | 证书/签名文件（`fcn_13C44` 开头 `ldr r1,[r4,0x10]` → `0x143BC` 加载） |
| `argv[5]` | 输出文件（`r7`，存到 `sp+0xC0`） |

`main` 的调用顺序：

```c
fcn_13C44(argv[1], argv[3], buf);     // 检查+解密+MD5
load_cert(argv[4]);                   // 0x143BC
memcpy(sp, sp+0xD8, 0xBD);            // 189 字节签名相关数据
fcn_14428(...);                       // magic + model
fcn_1410C(argv[1], argv[2], buf2);    // 解密到输出
```

> 具体哪个文件是 RSA 公钥、哪个是 AES key，还没有在调用方
> `rrm_bcm_arm` 里逐行确认；但 `argv[3]` 一定是 key 文件（偏移 0x6C）。

---

## 2. 校验流程

`main` 依次调用：

```
fcn_13C44(argv[1], argv[3], buf)   → 检查镜像 + 解密 + MD5
    if fail: "Image Check failed!"
fcn_14428(...)                      → 检查 magic + model
    if fail: "Invalid image signature"
fcn_1410C(...)                      → 解密到输出文件
    if fail: "Failed to decrypt the image"
```

### 2.1 `fcn_13C44` 做的事（从字符串和调用看）

```
Checking image
Opening Image
Reading Key
Reading in the Signature
Decrypting image
Checking image md5
Checksum missmatch
```

关键步骤：

1. 打开镜像（`fopen(..., "rb")`）；
2. 打开 **key 文件**（`argv[3]`），`fseek` 到 **偏移 0x6C** 读密钥材料；
3. 读 **0x100 字节** 的签名块；
4. 用 key + `AES_cbc_encrypt` 解密；
5. 对解密结果算 **MD5**，和签名块里的 hex 校验值比较。

### 2.2 `fcn_14428`：magic + model 检查

反汇编里能直接看到两个 32 位常量（大端转换后比较）：

```
0x112358D1
0x52237598
```

不匹配就打印：

```
Invalid Embedur Signature
```

然后做 **32 字节的 model 字符串比较**：

```
Model check: %s / %s
strncmp(model_in_image, expected_model, 0x20)
```

也就是说镜像是 **按型号绑定** 的。

### 2.3 加密原语

二进制里静态链接了 OpenSSL 1.0.1j，符号表里能看到：

```
AES_cbc_encrypt     ← 实际使用的 AES 模式
AES_encrypt / AES_decrypt
d2i_PKCS7           ← PKCS#7/CMS 解析
MD5（"Checking image md5" / "Checksum missmatch"）
RSA / CMS / PKCS7 相关错误字符串
```

**即：AES-CBC + MD5 + PKCS#7（RSA）签名结构。**
注意这里用的是 **MD5**，不是 SHA-256（和 `fw_upgrade` 那条链不同）。

---

## 3. 镜像布局（目前能确定的部分）

```
偏移 0x000      镜像头（含 magic 0x112358D1 / 0x52237598、model[32]）
…
偏移 0x06C      key 文件里的密钥偏移（不是镜像偏移）
…
偏移 ???        0x100 字节签名块
…
                 加密载荷（AES-CBC）
```

> 0x100 字节签名块的具体位置还没从 `fseek` 参数里完全定死；
> `fcn_13C44` 里能看到 `fseek(file, 0x100, ...)` 和一次 `malloc(0x100)`。

---

## 4. 和 `fw_upgrade` 的区别

| | `fw_upgrade`（整机固件） | `image_manager`（云代理升级） |
|---|---|---|
| 入口 | web / TR-069 | EmbedUR 代理 |
| 校验 | BCM tag 或 SHA-256 + RSA（`libcms_util`） | magic + model + MD5 + PKCS#7 |
| 镜像 | `]Cot` 容器 + 64 KB 签名块 | 自定义头 + 0x100 签名块 |
| 加密 | 通常不加密（签名） | **AES-CBC 加密** |
| 公钥 | 在 `libcms_util` | `sig_key.pub`（RSA-2048） |
| 失败回退 | `BOOT_SET_OLD_IMAGE` | 由代理决定 |

两条链互不复用。

---

## 5. 安全观察

1. **MD5 做完整性校验**：MD5 已不适合做安全校验，但这里还有 PKCS#7/RSA；
   实际强度取决于 RSA 验签是否真的执行（`d2i_PKCS7` 存在，但没逐函数确认）。
2. **magic 常量是固定值**：`0x112358D1` / `0x52237598` 可以在镜像里伪造，
   它们只是“格式标记”，不是签名。
3. **model 绑定**：32 字节型号比较，防止把别的机型镜像刷进来。
4. **AES-CBC 密钥来自 key 文件**：key 文件由云端下发/代理保存，
   如果 key 文件可被替换，加密层就形同虚设。
5. **这是第二条远程升级链**：即使 `fw_upgrade` 有签名校验，
   EmbedUR 代理仍可以通过 `image_manager` 走另一条路径。

---

## 6. 还没解的

- key 文件里偏移 0x6C 处的密钥长度（128/192/256）与派生方式。
- 0x100 字节签名块的确切字段布局（magic 之外的长度/哈希/签名）。
- PKCS#7 验签是否强制执行、失败是否真的会阻止写盘。
- `rrm_bcm_arm` 调用 `image_manager` 时的完整 argv。

---

## 7. 证据索引

| 内容 | 地址/位置 |
|---|---|
| `main` | `0x13878`（`argc != 6`） |
| 镜像检查/解密/MD5 | `fcn_00013C44` |
| magic + model 检查 | `fcn_00014428`（`0x112358D1` / `0x52237598`） |
| 解密到文件 | `fcn_0001410C` |
| AES-CBC | 符号 `AES_cbc_encrypt` |
| PKCS#7 | 符号 `d2i_PKCS7` |
| 公钥 | `sig_key.pub`（RSA-2048） |
| 字符串 | "Checking image"、"Invalid Embedur Signature"、"Checksum missmatch" |
