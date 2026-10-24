# Singtel Mesh Router 的固件升级链路

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b，BCM963138）
> 材料：解包后的 rootfs（`/bin/fw_upgrade`、`/lib/libcms_util.so`、`www/upgrade.htm`）
> 固件样本：`WE410443-ST_v6.02.00_build14.trx`（14,626,816 字节）

---

## 0. 一句话结论

web 上传的固件最终交给 **Broadcom 的 `libcms_util.so`** 验证并写入：

```
web 表单
  → upload.cgi / cgi-bin/upgrade.exe
  → httpd（把镜像放共享内存）
  → /bin/fw_upgrade <len> [分区]
       ├─ arca_validateImage()        ← BCM tag / CRC / chip id / RSA 签名
       ├─ arca_writeValidatedImageEx()
       └─ devCtl_setImageState()      ← A/B 分区切启动状态
  → reboot
```

**校验是真实存在的**：非 Broadcom tag 的镜像会走 **SHA-256 + RSA 数字签名**；
Broadcom tag 镜像则走 **tag CRC + 长度 + 芯片 ID**。

---

## 1. 升级入口（web）

`www/upgrade.htm`：

```html
<form enctype="multipart/form-data" method="post"
      action="/cgi-bin/upgrade.exe">
  ...
  <input type="file" name="plcfile">
</form>
```

提交的参数：

```js
cmd:''   uploadtype:1
```

上传完成后页面轮询 `ARC_SYS_TempUpgradeResult`：

```js
var upgrade_result='<% nvram_get_tmp(ARC_SYS_TempUpgradeResult); %>';
```

`httpd` 里的相关字符串：

```
FirmwareUpload
Illegal image size %d.  Image size must not be greater than %d.
ARC_SYS_SIMPLE_FW_UPGRADE init: %s
ARC_SYS_SIMPLE_FW_UPGRADE done: %s
******** %s-%d: Special FW allows upgrade ROM via Web GUI
/bin/fw_upgrade 5
/bin/fw_upgrade 6
```

> `5` / `6` 是 **两个镜像分区号**（A/B）。Web 升级一次写“非当前启动”的那一块。

---

## 2. `fw_upgrade` 做什么

`/bin/fw_upgrade`（ELF，9 KB）只是一层包装，真正干活的是
`/lib/libcms_util.so`。它的字符串和调用：

```c
arca_validateImage(img, len, ...);
arca_writeValidatedImageEx(...);
cmsImg_getImageVersion(...);
devCtl_setImageState(...);
devCtl_getImageState(...);
devCtl_getBootedImageId(...);
devCtl_getBootedImagePartition(...);
```

辅助动作：

```sh
echo %d > /data/sw_size_0          # 记录镜像大小
echo %s > /data/sw_version_%d      # 记录版本（按分区）
touch /tmp/swdl/arc_write_ok       # 写成功
touch /tmp/swdl/arc_write_fail     # 写失败
```

失败时会：

```
fw_upgrade fail! - set BootState back to orginal state %d
fw_upgrade: BOOT_SET_OLD_IMAGE - use old image to boot up, and wait for activation
```

即 **写失败不会把设备变砖**，会把启动状态切回旧镜像。

用法（二进制里的 usage）：

```
fw_upgrade fw_len (fw_len>0)
fw_upgrade fw_len Partition (fw_len>0)
fw_upgrade 0 FilePath
fw_upgrade 0 FilePath Partition
```

镜像通过 **System V 共享内存** 从 httpd 传进来：

```
echo 0x3C00000 > /proc/sys/kernel/shmmax
shmget(0x12345, 0x3C00000, IPC_CREAT | 0666)
shmat(shmid, NULL, 0)
memset(buf, 0, 0x3C00000)
read(upload_fd, buf, size)
```

- **key = `0x12345`**
- **size = `0x3C00000`（60 MB）**
- **权限 = `0666`（任何本地进程都能 attach/读写）**
- 升级期间还会 `arc_led power on`、`arc_led power_r off`
- 错误写 `/tmp/httpd_err.log`

★ **安全点**：`0666` 的共享内存意味着本机任何进程都能在上传完成到
`fw_upgrade` 读取之间**篡改固件镜像**（或读取它）。虽然路由器上通常没有
普通用户，但这仍是一个本地攻击面。

---

## 3. `libcms_util.so` 的校验逻辑

### 3.1 Broadcom tag 路径

`cmsImg_isBcmTaggedImage()` 与 `verifyBroadcomFileTag()`：

```c
/* img[0xEC] 是前 0xEC 字节的 CRC32 */
if (*(uint32_t *)(img + 0xEC) != crc_getCrc32(img, 0xEC, -1))
        → 不是合法的 Broadcom 镜像

/* img[0x3E] 是 ASCII 的数字：totalImageLen */
total = atoi(img + 0x3E) + 0x100;
```

也就是说，Broadcom tag 的结构是：

```
0x000  …                       tag 头（含 magic/version）
0x03E  "12345678\0"            totalImageLen（ASCII）
0x0D8  …                       保留/其他字段
0x0EC  u32                    前 0xEC 字节的 CRC32
0x100  …                       镜像数据
```

`cmsImg_parseImgHdr()` 还会打印：

```
tagVersion: %02x %02x %02x %02x
endian: %s
totalImageLen: %s
cfeAddress: ...
```

### 3.2 非 Broadcom tag 路径

`arca_validateImage()` 的反汇编（`0x12BE8`）：

```c
if (len <= 0x100) return 0;

if (verifyBroadcomFileTag(img, 1, len) == 0) {   /* 是 BCM tag */
    if (len <= flash_size + tag_size) ok;
} else {
    if (len <= 0x10000) return 0;

    /* 1) 数字签名 */
    if (arca_verifyDigitalSignature(img, len) != 0) return 0;

    /* 2) 尾部签名块：len - 0x10000 - 0x14 */
    r7 = len - 0x10000 - 0x14;
    sl = img + r7;
    if (*(uint32_t *)sl != crc_getCrc32(img, r7, -1)) return 0;

    /* 3) 芯片 ID */
    if (*(uint32_t *)(sl + 8) != devCtl_getChipId() &&
        *(uint32_t *)(sl + 8) != 0x63138) return 0;

    /* 4) 64 字节 RSA 签名 */
    arca_getSignature(img, r7, sig, 0x40);
    ... RSA 验签 ...
}
```

库里能看到的原语：

```
sha256_init / sha256_update / sha256_final
RSAPublicDecrypt / RSAPublicEncrypt
R_VerifyBlockSignature / R_VerifyPEMSignature
arca_verifyDigitalSignature
```

**结论：镜像尾部有 64 KB 的签名块 + 20 字节头，里面含 CRC32、芯片 ID、RSA 签名。**
（`0x10000` = 65536 = 64 KB，正好解释 `.trx` 最后那 64 KB 几乎全是零/签名数据。）

---

## 4. `.trx` 容器格式（Arcadyan `]Cot`）

样本开头：

```
00000000  5d 43 6f 74 00 30 de 00 3b 0d e9 d5 00 00 01 00   ]Cot.0..;.......
00000010  1c 00 00 00 1c 00 2d 00 00 00 00 00 27 05 19 56   ......-.....'..V
```

解析：

| 偏移 | 值 | 含义 |
|---:|---|---|
| `0x00` | `]Cot`（`5d 43 6f 74`） | 容器魔数 |
| `0x04` | `0x00DE3000`（LE） | 镜像长度（= 文件大小 − 0x10000） |
| `0x08` | `0xD5E90D3B` | 32 位校验值（**算法尚未对上**，见 §7） |
| `0x0C` | `0x00010000` | 版本 / 标志 |
| `0x10` | `0x0000001C` | **kernel 偏移** = 28 |
| `0x14` | `0x002D001C` | **rootfs 偏移** = 0x2D001C |
| `0x18` | `0x00000000` | 保留 |
| `0x1C` | `27 05 19 56` | **uImage 魔数**（大端 `0x27051956`） |

实际布局（逐段验证过）：

```
0x00000  ]Cot 头（28 字节）
0x0001C  uImage（kernel）
           magic  0x27051956
           hcrc   0x5477A2E7   ← CRC32(header) 校验通过 ✓
           size   0x002CFFC0   （约 2.95 MB）
           dcrc   0xC7F8F6C5   ← CRC32(data) 校验通过 ✓
0x2D0000 0xFF 填充（0x1C 字节）
0x2D001C squashfs（rootfs）  magic "hsqs"
0xDE3000 结束（= 文件大小 − 0x10000）
0xDE3000 – 0xDF3000：64 KB 签名块（尾部）
```

★ **uImage 的 hcrc 和 dcrc 都是对的**，说明 kernel 段是完整的标准 uImage；
rootfs 是紧随其后的 squashfs（`hsqs`）。

这和 `arca_validateImage` 的 `len - 0x10000 - 0x14` 完全对得上 ——
**最后的 64 KB 就是签名块**。

### 关于 `0x08` 的 32 位校验值

先确认了设备自己的 CRC 实现：`/lib/libbcm_crc.so` 的 `crc_getCrc32`
是**标准反射 CRC-32（表驱动，poly 0xEDB88320，无最终 XOR，init 由调用方给）**：

```c
crc = table[(crc ^ byte) & 0xff] ^ (crc >> 8);
```

用这个精确实现 + 多种多项式，对 `0xD5E90D3B` 做过以下尝试：

| 维度 | 试过 |
|---|---|
| 多项式 | IEEE / Castagnoli / Koopman / CRC-32Q / XFER |
| 方向 | 反射 / 非反射 |
| init | 0 / 0xFFFFFFFF |
| 最终 XOR | 有 / 无 |
| 范围 | 整段 / 去签名块 / payload / kernel / rootfs / rootfs+96 |
| 其它 | Adler-32、MD5/SHA1/SHA256 前后 4 字节、两段 CRC 的 XOR/加/减 |

**全部未命中。** 说明它不是“标准 CRC + 连续区间”的组合；
可能是打包工具的自定义校验，或覆盖范围包含/排除了某些头字段。
如实记录在这里，不再猜。

> 之前我一度因为“尾部 98.96% 是零”而把“签名块”这个判断撤回了；
> 现在从校验函数的反汇编看，**它确实是签名块**，只是大部分是零填充。

---

## 5. 特殊模式：`ARC_SYS_SIMPLE_FW_UPGRADE`

`httpd` 里还有一段：

```
ARC_SYS_SIMPLE_FW_UPGRADE init: %s
ARC_SYS_SIMPLE_FW_UPGRADE done: %s
******** %s-%d: Special FW allows upgrade ROM via Web GUI
```

这说明存在一种 **“simple firmware”**：它不是常规 rootfs 镜像，而是
**允许通过 Web 升级 boot ROM / 引导器**的特殊包。相关配置键是
`ARC_SYS_SIMPLE_FW_UPGRADE`（在 `.glbcfg` 里可以看到/设置）。

对维修的意义：**只要 Web 还能进，就有机会把 bootloader 也刷回去** ——
这也是 CFE Web 恢复模式之外的第二条路。

---

## 6. 安全观察

1. **签名是强制的**：非 BCM tag 镜像必须带 RSA 签名，公钥不在用户手里
   （`sig_key.pub` 那一套在 EmbedUR 代理里，属于另一条升级链）。
2. **Broadcom tag 路径只校验 CRC + 芯片 ID，不验签** ——
   如果攻击者能构造一个合法的 BCM tag，就能绕过数字签名。
   （这是 Broadcom 平台的历史设计，不是 Arcadyan 独有的问题。）
3. **写失败会回退**：`BOOT_SET_OLD_IMAGE`，不会把设备变砖。
4. **A/B 分区**：`fw_upgrade 5` / `6` 对应两块镜像，升级写非当前块。
5. **Web 升级入口**：`/cgi-bin/upgrade.exe`，字段名 `plcfile`，
   需要 admin 登录；上传大小有上限（httpd 会拒绝）。
6. **`ARC_SYS_TempUpgradeResult`** 是明文结果，页面直接读。

---

## 7. 已解 / 未解

**已确认：**

- 升级入口、参数、结果字段
- `fw_upgrade` 的参数与共享内存机制
- A/B 分区与失败回退
- `libcms_util.so` 的校验流程（BCM tag / CRC / chip id / RSA / SHA-256）
- `.trx` = `]Cot` + uImage + 64 KB 签名块
- 签名块位置 = `len - 0x10000`，与校验代码一致

**未解（如实记录）：**

- `]Cot` 头 `0x08` 处的 32 位校验值算法 —— 试过 zlib CRC32（多种 init/xor）、
  CRC-32/MPEG-2、BZIP2、POSIX、JAMCRC，都对不上；
  可能是厂商自定义多项式，或只覆盖某个子区间（kernel/rootfs 分段）。
- 64 KB 签名块内部的精确字段布局（CRC 在 `sl`、chip id 在 `sl+8` 已确认，
  其余偏移还没逐字节核对）。
- `image_manager`（EmbedUR 那条链）的加密容器格式。

---

## 8. 证据索引

| 内容 | 位置 |
|---|---|
| web 升级页 | `www/upgrade.htm`、`www/cgi/cgi_upgrade.js` |
| 升级执行 | `/bin/fw_upgrade`（ELF） |
| 校验库 | `/lib/libcms_util.so` → `arca_validateImage` @ `0x12BE8`、`cmsImg_isBcmTaggedImage` @ `0x13358`、`verifyBroadcomFileTag` @ `0x1224C`、`cmsImg_parseImgHdr` @ `0x133FC` |
| 签名原语 | `sha256_*`、`R_VerifyBlockSignature`、`RSAPublicDecrypt` |
| 结果字段 | `ARC_SYS_TempUpgradeResult`、`ARC_SYS_SIMPLE_FW_UPGRADE` |
| 样本 | `WE410443-ST_v6.02.00_build14.trx`（`]Cot`，0xDE3000 + 0x10000） |
