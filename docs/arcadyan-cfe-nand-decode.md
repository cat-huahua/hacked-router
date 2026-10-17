# Singtel Mesh Router（Arcadyan WG9116AEAC23-ST）固件解码

2026-10-17。**这是一台之前完全读不了的设备 —— 现在整条链路（引导器 + 内核 + 配置 + 设备树）都解开了。**

## 0. 起因：一个"读不出来"的 NAND 镜像

素材：`singtel_jffs2.img`（3,538,944 字节），从一个 NAND 镜像里切出来。
用常规手段全部失败：

| 常规做法 | 结果 |
|---|---|
| `file` | data（认不出来） |
| 按 JFFS2 解析（大端） | **0 个合法节点** |
| 按 UBI / squashfs 解析 | 无 |
| 熵 | 前半 5~6，后半 7.99（像加密） |
| 开头 | ARM 异常向量表 `25 00 00 ea` + CFE 字符串 |

**看起来像"CFE 引导器 + 一段加密数据"。** 但真相不是这样。

## 1. ★ 关键发现：JFFS2 用了**小端**存字段

在"高熵区"里发现 `85 19 02 e0 0c 06 00 00` 这样的序列。JFFS2 节点的标准布局是

```
magic(u16 BE) | nodetype(u16 BE) | totlen(u32 BE) | hdr_crc(u32 BE)
```

而这里把这 12 字节**整体按小端**解释就全对了：

| 字段 | 原始字节 | 小端解释 | 标准大端解释 |
|---|---|---|---|
| magic | `85 19` | **0x1985** ✓ | 0x8519 ✗ |
| nodetype | `02 e0` | **0xE002**（JFFS2_NODETYPE_INODE）✓ | 0x02E0 ✗ |
| totlen | `0c 06 00 00` | **1548** ✓ | 0x060C0000 ✗ |
| hdr_crc | `7d f7 da c2` | 见下 | — |

**另一处坑：CRC 算法。** JFFS2 的 CRC 是 Linux 内核的 `crc32()`，**和 zlib 的约定不同**
（内核版本不做首尾取反）：

```python
def jffs2_crc(data):
    return (zlib.crc32(data, 0xFFFFFFFF) ^ 0xFFFFFFFF) & 0xFFFFFFFF
```

**用四个已知节点反推验证：全部匹配** ✓✓
（`zlib.crc32(data)` 直接算是不匹配的 —— 这一点如果搞错，会得出"解析失败"的错误结论。）

**修正这两点后：746 个合法节点，类型分布 739×INODE(0xE002) + 6×DIRENT(0xE001)。**

> 为什么是小端？这是 NAND 镜像在提取/烧写环节被按 32 位字读取导致的端序错误。
> **不是加密，也不是损坏** —— 只是字节序。

## 2. 提取出完整固件载荷

工具：`jffs2_extract.py`（本目录）

```
vmlinux.lz          2,423,720 字节   ← 内核（前 20 字节是 BRCM 头，之后是 LZMA）
cferam.000            501,948 字节   ← ★ CFE 引导器（RAM 镜像）
963138_debug.dtb        2,419 字节   ← 设备树（BCM963138）
image_signature            16 字节   = "WG9116AEAC23-ST"
image_version               9 字节   = "v5.02.00"
etc/                                  （目录）
```

**身份确认**：`v5.02.00` 与 `WG9116AEAC23-ST` 正好对应 Singtel 官方那份
`Singtel-MeshRG_v5.02.00_build09b_20230607_sign.w` ✓

### 内核怎么解

`vmlinux.lz` 开头是一个 20 字节的 BRCM 头，LZMA 流从偏移 **20** 开始：

```
00 80 00 c0 | 00 80 00 c0 | 94 fb 24 00 | 42 52 43 4d ("BRCM") | 00 00 00 00
                             长度=2423700                        ← 有效数据长度
偏移 0x14 起: 6d 00 00 40 00 ...   ← props=0x6d, dict=4MB（LZMA alone）
```

解出 **6,472,384 字节内核**，并从 `IKCFG_ST…IKCFG_ED` 段解出 **74,636 字节的内核 config**。

### 内核 config 里的关键结论

```
# CONFIG_ARC_UBIFS_FS_CRYPTO is not set     ← 这台设备的 rootfs 不加密（与实测一致）
（没有 CONFIG_ARC_SQUASHFS_FS_CRYPTO）      ← ★ 确认那个 squashfs 加密是【extender 独有】的
CONFIG_CRYPTO_AES=y / ECB=y / CBC=y
```

**对照价值**：同一家厂商有 `ARC_UBIFS_FS_CRYPTO` 和 `ARC_SQUASHFS_FS_CRYPTO` 两个加密选项。
这台 RG 两个都不用（rootfs 是明文 UBIFS，所以能直接解）；
extender 用了 squashfs 那个（所以它的 rootfs 加密）✓ 与 [arcadyan-singtel-config-format.md](arcadyan-singtel-config-format.md) 完全吻合。

### 设备树（dtc 可反编译）

```
compatible = "brcm,bcm963138";   model = "Broadcom BCM963138";
chosen bootargs = "root=ubi:rootfs_ubifs ubi.mtd=0 rootfstype=ubifs
                   console=ttyS0,115200 debug irqaffinity=0 init=/sbin/preinit
                   coherent_pool=1M cpuidle_sysfs_switch cma=0M bcm63xx_cons.arc_dump=1"
cpu: arm,cortex-a9 ×2 / PL310 cache / nand: brcm,brcmnand-v7.0
```

## 3. ★ CFE 引导器（`cferam.000`）里的东西

### ① Web 恢复模式（"Boot-P Mode"）

CFE 内嵌了一个 HTTP 服务，页面与接口：

```
/login.html  + login.cgi        ← 用户名/口令登录
/upload.html + upload.cgi       ← ★ "Update Software"（刷固件）
resetcfg.cgi                    ← ★ "Restore to Factory Defaults"
/loginfail.html  /uploadinfo.html
```

**⚠️ 但这个 CFE 会校验镜像签名**：

```
Authenticating vmlinux.lz ...
vmlinux.lz cannot be authenticated. Stopping
```

**所以即使进了 Web 模式，也只能刷【官方签名的】固件** —— 和 [singtel-firmware-analysis.md](singtel-firmware-analysis.md)
里"只接受签名镜像"的结论一致。恢复出厂（`resetcfg.cgi`）不受此限。

### ② 串口控制台

```
Copyright (C) 2000-2015 Broadcom Corporation.
Chip ID: BCM%s, ARM Cortex A9 Dual Core: %dMHz
PROMPT
CFE>
```

有 `CFE>` 提示符；命令包括 `e n/p/a`（擦 nvram / 持久存储 / 除 bootrom 外全部）、
`loadb`（Kermit 串口/网络加载）、`ws`（写 flash）等。

### ③ ★ 出厂配置菜单 —— 板级数据的完整字段表与默认值

串口菜单里有 `## ARC: set default board parameters. ##`，逐项询问并显示默认值。
**这台设备的全部可配置板级字段**：

```
ARC WLAN Country Code / Territory Code
ARC Temp Boot Flag / Image Clone Flag [0|12|21] / MP Test
ARC WLAN 2.4G Password / 5G Password
ARC GUI Password                 ← 管理界面密码
ARC WiFi Backhaul Password
ARC WiFi 2.4G SSID / 5G SSID / Backhaul SSID
ARC Serial Number / Manuf Model / Manuf HW Version
GPON Serial Number / GPON Password
Device Pin                       ← WPS PIN
Board Id / Number of MAC Addresses / Base MAC Address
PSI Size / System Log Size / Auxillary File System Size Percent
```

**出厂默认值（`*** default values ***` 区）**：

| 项 | 默认值 |
|---|---|
| 型号 | `WG9116AEAC23-ST` |
| 型号名 | `Arcadyan Generic` |
| 序列号 | `ARCADYAN2015000001` |
| 默认 2.4G SSID | `Mesh_Router_2.4G` |
| 默认 5G SSID | `Mesh_Router_5G` |
| 默认回程 SSID | `RG_Backhaul` |
| 默认 WPS PIN | `12345670` |
| 默认 Base MAC | `00:10:18:00:00:00`（Broadcom OUI） |
| 其他候选默认串 | `0000000000` `1234567890` `ABCDEFGHIJ` `0987654321` `0016814500` `NOSLIC` `ARSA20170001` `ZZ/01` `BRCM12345678` |

> `BRCM12345678` 出现在默认值区，**疑似 CFE/串口默认口令**（未验证）。
> 这些默认值都来自**官方公开固件**，且 CFE 入口需要**串口或同网段访问**。

**★ 实际意义**：这台设备的**出厂默认 SSID/回程名/WPS PIN 是固定的**（不像 extender 那样按序列号派生）。
所以如果一台设备没改过设置，它的 WiFi 名就是 `Mesh_Router_2.4G` / `Mesh_Router_5G`。

## 4. 方法论小结（可复用）

| 症状 | 真正的原因 | 怎么确认 |
|---|---|---|
| "认不出文件系统" | **字段字节序不对**（这里是小端） | 拿 magic 试两种端序 + **用 CRC 反推并验证** |
| "CRC 总是不匹配" | 用了 zlib 的约定，而 JFFS2 用**内核约定** | `zlib.crc32(d,0xFFFFFFFF) ^ 0xFFFFFFFF` |
| "文件提取出来全是零" | **把"最高版本"当成唯一分块** —— JFFS2 一个文件是**多版本节点**构成的 | 按**版本升序**依次应用各块（后写覆盖） |
| "INODE 字段全错位" | `uid`/`gid` 是 **u16**，写成 u32 会让后面所有字段错 2 字节 | 格式串 `IIIHH` 不是 `IIIIHH` |

**这四条每一条都会表现为"解析失败/结果是垃圾"，而看起来都像"数据被加密了"。**
所以我现在的习惯是：**每解出一步就立刻用已知量验证**（CRC、magic、文件大小、字符串），
不验证就直接往下走，很可能整条链都建在错的偏移上。

---

# 附：同一套方法用于 NETGEAR DSL-AC87VG（2026-10-17）

**结论：`jffs2_extract.py` 不需要改一行就能解另一台设备** —— 证明这个"小端 JFFS2"不是个例，
而是这一代 Broadcom/Arcadyan 固件的**共同特征**。

## 素材与结果

```
FW_DSL_AC87VG_10518305.zip → DSL-AC87VG_v1.05.18_build305_cferom_fs_image_128_ubi.w  (55MB)
FW_DSL_AC87VG_10519307.zip → DSL-AC87VG_v1.05.19_build307.w                         (55MB)
```

```
$ python3 jffs2_extract.py DSL-AC87VG_v1.05.19_build307.w -o fs
  试 大端(标准)   节点 0     CRC通过 0
  试 小端(非标准) 节点 617   CRC通过 616     ← 自动选中
  写出 4 个文件:
    cferam.000     420620 字节
    vmlinux.lz    2002927 字节
    image_version       8 字节   = "0.01.01"
    etc/              （目录）
```

`vmlinux.lz` 同样是 **20 字节 BRCM 头 + LZMA**（偏移 20）：

```
BRCM 头: 0xC0008000 0xC0008000 2002907 "BRCM" 0     ← 第三个字段 = 有效数据长度 2002907
偏移 0x14: 6d 00 00 40 ...                          ← props=0x6d, dict=4MB
→ 解出 8,610,404 字节内核，config 60,384 字节
```

## 与 Singtel Mesh Router 的对比

| | Singtel Mesh Router | NETGEAR DSL-AC87VG |
|---|---|---|
| JFFS2 端序 | **小端**（非标准） | **小端**（同样）✓ |
| 内核容器 | BRCM 头 + LZMA | BRCM 头 + LZMA（同） |
| 内核里的品牌 | — | **没有 NETGEAR 字样** |
| 加密选项 | 无 `ARC_SQUASHFS_FS_CRYPTO` | 无 |
| rootfs | UBIFS（**不加密**，已完整解出） | UBI 卷 0，398 LEB / 48MB |

**判读**：`DSL-AC87VG_..._.w` 里装的是**Broadcom/Arcadyan 的 SDK 参考构建**，
不是 NETGEAR 自己那套（内核里没有 NETGEAR 品牌串）。换牌子主要换的是 rootfs（web UI/配置）。

## 这次**没能**做完的（如实记录）

DSL 的 rootfs 是 48MB 的 UBIFS，**UBIFS 的完整提取需要专门的解析器**
（超块 + master node + index B-tree + LEB 重组），而当前环境里没有 `ubireader` 之类的工具。

退而求其次做了**原始 LEB 字符串扫描**，拿到 8142 条可读串（未压缩的碎片），
能看到文件清单与模板（`/usr/sbin/httpd`、`/usr/sbin/key.pem`、`/var/ipsec/psk.txt`、
`chap-secrets`、`Main_Password.htm`、`arca.dbus.homeplud:MSG_HOMEPLUG_PASSWORD_SET`、
`#USERNAME PROVIDER PASSWORD IPADDRESS` 模板），**但没有捞出默认口令**
（UBIFS 里的文件多数是压缩的，所以要完整提取才能定论）。

> **下次要接着做的话**：装 `ubi_reader`（`pip install ubi_reader`）或用 `ubireader_extract_files`，
> 就能把卷 0 完整解出来。这一步不需要硬件。
