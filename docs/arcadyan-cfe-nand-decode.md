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
| 默认 WPS PIN | `VENDOR_WPS_PIN_HERE` |
| 默认 Base MAC | `00:10:18:00:00:00`（Broadcom OUI） |
| 其他候选默认串 | `0000000000` `VENDOR_BACKHAUL_PSK_HERE90` `ABCDEFGHIJ` `0987654321` `0016814500` `NOSLIC` `ARSA20170001` `ZZ/01` `BRCMVENDOR_BACKHAUL_PSK_HERE` |

> `BRCMVENDOR_BACKHAUL_PSK_HERE` 出现在默认值区，**疑似 CFE/串口默认口令**（未验证）。
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

---

# 附二：DSL-AC87VG 的 rootfs 也全解了（并查出血统）

上面"没做完"的那步补上了 —— **不需要硬件，装个 `ubi_reader` 就行**：

```bash
python3 -m venv /tmp/ubienv && /tmp/ubienv/bin/pip install ubi_reader
# 先把 UBI 区切出来（ubi_reader 自己判边界会失败）
python3 -c "import pathlib;d=pathlib.Path('DSL....w').read_bytes();\
            pathlib.Path('dsl_ubi.img').write_bytes(d[d.find(b'UBI#'):])"
/tmp/ubienv/bin/ubireader_extract_images -o out dsl_ubi.img   # → img-0_vol-rootfs_ubifs.ubifs
/tmp/ubienv/bin/ubireader_extract_files  -o fs  img-0_vol-rootfs_ubifs.ubifs
```

**结果：3031 个文件 / 93 MB。** 卷名 `rootfs_ubifs`。

## ★★ 血统：这套固件是 **ASUSWRT** 改的

解出来一看，**里面一行 NETGEAR 字样都没有**：

| 痕迹 | 是什么 |
|---|---|
| `rom/.asusrouter` | `#!/bin/sh` + `# ASUS app autorun script` ← **ASUSWRT 的标志文件** |
| `usr/lib/libasusnvram.so` | ASUS 的 nvram 库 |
| `sbin/arc_asuslink` / `arc_ASUS_updateValue` | 连前缀 `arc_`（Arcadyan）都只加在 ASUS 的东西前面 |
| `www/images/asustitle.png` / `Advanced_ASUSDDNS_Content.htm` | ASUS 的 web 资源 |
| `usr/bwdpi/ntdasus2014.cert` / `www/tm_eula_*.htm` | TrendMicro AiProtection（ASUS 的合作方） |
| **187 个 `ASUS_*` 配置键** | ASUSWRT 的配置命名空间 |

文件计数：**ASUS 相关 109 个 + 77 个含 "asus"**、**NETGEAR **0** 个**、Arcadyan 4 个。

**判读**：DSL-AC87VG 装的是 **Broadcom/ASUS 参考固件（ASUSWRT）经 Arcadyan 改制**，
NETGEAR 只提供了型号名。⇒ **整套 ASUSWRT 的公开知识（配置键、web UI、工具）都能直接用在这台设备上。**

## ★ 管理密码：`SHA512_hex(MD5_hex(密码))`，默认值 `admin`

`glbcfg.dft`（出厂默认配置，**明文**）里：

```
ARC_SYS_LoginName = edbd881f1ee2f76ba0bd70fd184f87711be991a0401fd07ccd4b199665f00761afc91731d8d8ba6cbb188b2ed5bfb465b9f3d30231eb0430b9f90fe91d136648
ARC_SYS_Password  = edbd881f1ee2f76ba0bd70fd184f87711be991a0401fd07ccd4b199665f00761afc91731d8d8ba6cbb188b2ed5bfb465b9f3d30231eb0430b9f90fe91d136648
ARC_SYS_LoginTimeout = 30
```

128 位十六进制 = **SHA-512**。`hashcat -m 1700` + crackstation 字典**秒破**：

```
edbd881f…136648  →  21232f297a57a5a743894a0e4a801fc3
```

而 `21232f297a57a5a743894a0e4a801fc3` **正是 MD5("admin")** —— 于是：

```
ARC_SYS_Password = SHA512_hex( MD5_hex( 明文 ) )      明文 = "admin"
ARC_SYS_LoginName 与 Password 完全相同  ⇒  默认账号密码都是 admin
```

> **★ 破解这类配置的工作流**（容易走弯路）：哈希是**两层**的。
> 用 `-m 1700`（SHA-512）破出来的"明文"**其实是 `MD5_hex(真密码)`**（一段 32 位十六进制），
> 还要再拿它当 MD5（`-m 0`）去查一次表，或者直接认出它就是常见口令的 MD5。
> 本次就是靠"认出 21232f29… 是 admin 的 MD5"直接得解的。

**同一家厂商，三台设备的密码存法都不同**：

| 设备 | 管理密码怎么存 |
|---|---|
| NETGEAR R7800（原厂） | `http_passwd` = 裸 SHA256 |
| Singtel Mesh Router | `ARC_SYS_Password` = **明文** `admin`（运行时由 `arc_board get gui-pwd` 覆盖） |
| **DSL-AC87VG** | `ARC_SYS_Password` = **SHA512(MD5(明文))** |

## ★ 三把**无口令保护**的厂商共用私钥

```
usr/sbin/key.pem                                889 字节  RSA-1024
usr/share/config/etc/config/cert/RootCA/rootca.key.pem     1679 字节  RSA-2048
usr/share/config/etc/config/cert/WebServer/webserver.key.pem 1679 字节  RSA-2048
```

三把**互不相同**（modulus 指纹各不同），**全部没有 `Proc-Type: ENCRYPTED` 头**，
即**明文私钥、且所有出厂设备共用同一套**。

其中 `rootca.key.pem` 是**厂商根 CA 的私钥** ——
拿到它就能为这类设备**签发可被信任的证书**（配合[冒充云端](singtel-firmware-analysis.md)
那条线：设备本来就不校验证书，现在连"签一个像样的"都不需要了）。

## 其它默认值

```
ARC_USB_ACCOUNT_0_Password   = admin
ARC_VO_SIPACC_0..5_Password  = **11** **12** **21** **22** **23** **24** **25**
ARC_VO_DECT_0..2_AucAuthKey  = 00,00,00,00,00,00,00,00,00,00,00,00,00,00,00,00   ← 全零
```

（DECT 的鉴权密钥**全零**，SIP 账号口令是 `**11**` 这种占位符 —— 都是出厂模板值。）

---

# 附三：把两个内核的**完整符号表**解出来了（`vmlinux` 深挖）

`strings vmlinux | grep` 只能捞到零星几个符号名 —— 因为内核把符号名**压缩**存储。
解出来之后一次能拿到几万个函数名。

## 三张表

```
kallsyms_token_table   256 个 NUL 结尾的「片段」（如 'oo' 'ig' 'init_' '_set_' 'lock_'）
kallsyms_token_index   256 个 u16 偏移，指回 token_table
kallsyms_names         每个符号 = [长度][长度个 token 索引]
                       （名字首字符是【类型】：T=全局代码 t=局部代码 r=只读数据 b=BSS）
```

## ★ 判据是踩了三次才对的（全记下来）

| 尝试 | 为什么不够 |
|---|---|
| ① "token 表 = 256 个递增 u16" | **整片零也满足** → 把零串误判成表（见过解出 256 个空 token 的"表"） |
| ② 加"≥200 个非空 token" | 表找到了 ✓，但还找不到 names 段的**对齐起点** |
| ③ "能连续解出 100 个合法字符的名字" | **错位解码同样能解出一大串**（见过 `initit_r__func_fiinit...`） |
| ④ 加"多样性 ≥150/200" | 仍不够 —— 见过 `init4_A` 重复 69 次却仍够唯一值的 |
| ⑤ **取"解出名字最多"的那个起点** | ✅ 正确的对齐能一路解到几万个，错位的几百个就断 —— **差异是数量级，所以稳** |

**⑤ 还要配两趟做**（否则逐字节长解太慢）：先每题只解 60 个快速筛候选，
再对候选长解比数量。另外候选列表**不能截断** —— 真正的对齐可能在很后面
（我就因为截断到 40 个候选而漏掉了它，解出 128 个垃圾名还以为成功了）。

## 结果

| 内核 | 版本 | 解出符号 | 开头符号（ARM 内核入口，可验证对齐正确） |
|---|---|---|---|
| Singtel Mesh Router | Linux **4.1.38** | **40,349** | `Tstext` `T_text` `t__create_page_tables` `t__turn_mmu_on` |
| NETGEAR DSL-AC87VG | Linux **3.4.11** | **17,483** | `Tasm_do_IRQ` `T_stext` `T__exception_text_start` |

**交叉校验**（用已知事实反验）：
- `down_timeout` 在 Mesh Router 的表里 ✓（它确实导出过这个符号）
- **`get_decrypt_keys` 不在** Mesh Router 的表里 ✓ —— 与"这台没有 `CONFIG_ARC_SQUASHFS_FS_CRYPTO`"完全一致

## 顺手挖出来的东西：Broadcom 的**板级参数 API**

```
Mesh Router(4.1.38):  213 条 Bp*  · 124 条 kerSys* · 58 条 brcm*
DSL-AC87VG (3.4.11):  194 条 Bp*  · 121 条 kerSys* · 68 条 brcm*
```

`Bp*` = Broadcom 的 **Board Parameter** 系列 —— 就是 `arc_board` 在 Broadcom 侧的对应物：

```
BpGetBoardId  BpGetBoardIdNameByIndex  BpGetAllPinmux  BpGetButtonInfo
BpGetAdslLedGpio  BpGetDectLedGpio  BpGetVoipDspConfig  BpGetDefaultOpticalParams
BpGetAFELDPwrBoostGpio  BpGet1ppsStableGpio  BpGetBatteryEnable ...
```

**价值**：这等于拿到了**这台设备能配哪些硬件参数**的完整清单 ——
比从字符串里捞要系统和完整得多。

工具：[`kallsyms_extract.py`](../kallsyms_extract.py)（两台真机内核上实测通过）

---

# 附四：DSL-AC87VG 的 CFE 出厂配置菜单（完整）

`cferam.000` 的串口控制台里有**两段** provisioning 菜单：

## ① `--- Set Arcadyan Manufacture Data ---`（字段名是 `Arcadyan *`，不是 `ARC_*`）

```
Arcadyan Serial Number            :        Invalid Serial Number
Arcadyan DECT RFPI                :
Arcadyan Manuf Model              :        Invalid Model Name
Arcadyan Manuf Hw_Ver             :        Invalid Hardware Version
Arcadyan Image Clone flag[0|12|21]:        Invalid flag
Arcadyan MPTEST                   :        Invalid value
Arcadyan WLAN Country Code        :        Invalid Country Code
Arcadyan WLAN Territory Code      :        Invalid Territory Code
```

**内联的出厂默认值**：

| 项 | 默认值 |
|---|---|
| 板名 | **`963138_GFAST`** ← ★ BCM963138 + **GFAST**（这是台 **G.fast** DSL 网关） |
| 序列号 | `ARCADYAN2015000001` |
| 型号 | `DSL-AC87VG` |
| 国家/版本 | `DE/01` |
| 语音芯片 | `Si32260_LCQC`（Silicon Labs Si32260 编解码器） |
| 其它 | `0016814500` · `BRCMVENDOR_BACKHAUL_PSK_HERE`（疑似默认口令） · `VENDOR_WPS_PIN_HERE`（默认 WPS PIN） |

> `963138_GFAST` 正好解释了我们解出的 `963138_debug.dtb` ✓

## ② Broadcom 板级参数

```
Board Id                          :    Invalid board ID
Number of MAC Addresses (1-32)    :    Invalid MAC addresses number: 1 - 32
Base MAC Address                  :    eg. 12:34:56:ab:cd:ef or 123456abcdef
PSI Size (1-128) KBytes           :    (1-64) Kbytes
Enable Backup PSI [0|1]           :
System Log Size (0-256) KBytes    :
Auxillary File System Size Percent:    (0-80)
GPON Serial Number / GPON Password:
MC / TM / DHD 0,1,2 memory allocation (MB)
Device Pin                        :    Invalid WPS Device Pin
Voice Board Configuration (0-#)   :
DECT Type Installed (0-#)         :    No DECT / Internal DECT / External DECT
Partition 1..4 Size (MB) (Data)   :    Invalid parition size
```

菜单行为：`Press: <enter> to use current value` / `'x' to exit this command` /
`%s; Try again!`（输错就重问）—— 这是**产线刷写时逐项确认**的界面。

---

# 附五：★ Web UI 的加密方案在两个设备上是**同一份代码**

从 DSL-AC87VG 的 rootfs 里翻出 `www/js/global.js`，发现它和 **Singtel Mesh Router**
的那份**是同一套代码** —— 连混淆过的 blob 都一字不差。

## 1. 登录哈希：`ArcMD5`

```js
function ArcMD5(_s){
    var s = calcMD5(_s);                    // MD5，输出 hex
    var shaObj = new jsSHA(s, "ASCII");
    s = shaObj.getHash("SHA-512","HEX");    // 再 SHA-512
    return s;
}
```

**`ArcMD5(x) = SHA512_hex(MD5_hex(x))`** —— 与 [singtel-mesh-login-lock.md](singtel-mesh-login-lock.md)
里那份逐行相同 ✓ 也与 [Arcadyan 配置](arcadyan-singtel-config-format.md)里
`ARC_SYS_Password = SHA512(MD5(明文))` 的存法一致 ✓

## 2. token：`ArcBase._t()`

```js
// 取页面里第一个 src 以 "data:" 开头的 <img>（那张 1×1 GIF），
// 对 src.substring(78) 做 base64 解码
ArcBase._tt = function(){ ... }
```

**混淆手法与 Mesh Router 完全相同**：base64 解码 → 每字节 XOR 3 → `unescape` →
去掉前 19 字符 → `eval`。**混淆串本身一字不差**（`ZXZtYHdqbG0mMTNkZndXbGhmbSYx...`）。

## 3. ★ 表单字段的"加密"：AES-CBC，**密钥就是同一页面里的 token，IV 全零**

```js
function do_encode(_s){
    var iv  = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0];   // ★ 全零 IV
    var k   = ArcBase._t();                          // ★ 密钥 = 页面里的 token
    var key = ArcAES.IntToByteArray(k, 32);
    var ct  = ArcAES.IntToByteArray(_s);
    var pt  = ArcAES.create('CBC', key, iv).encrypt(ct);
    return ArcAES.byteArrayToHTML(pt);
}
// do_decode 是反过程（hex 输入、长度必须是 16 的倍数、否则原样返回）
```

**这是混淆，不是保密。** 因为：

- 密钥 `k` **就在同一个页面里**（那张 GIF 的 data URI）——
  任何能看到页面的人都能拿到密钥和算法；
- IV **固定全零**，没有随机性；
- 它保护的只是"密码不在浏览器的表单提交里明文出现"这件事
  （防的是**肩窥/代理日志**，不是防攻击者读页面）。

> 顺带：`do_decode` 的入参要求 `length % 16 == 0` 且是 hex，否则**原样返回** ——
> 所以拿到配置项密文时，判断"有没有被加密"的判据就是**长度是否 16 的倍数且是纯 hex**。

## 4. 意义：三台设备共享同一套前端

| 设备 | `ArcMD5` | `ArcBase._t` 混淆串 | 表单加密 |
|---|---|---|---|
| Singtel Mesh（extender） | ✓ 相同 | ✓ 相同 | `encode()` 每字符 +97 |
| Singtel Mesh Router | ✓ 相同 | ✓ **一字不差** | `do_encode` AES-CBC |
| NETGEAR DSL-AC87VG | ✓ 相同 | ✓ **一字不差** | `do_encode` AES-CBC |

**⇒ 解一个就等于解全部。** 这也是这一路"同一家厂商多台设备"反复印证的事：
`arc_glbcfg` 的结构、`glbcfg` 的明文格式、`arc_board` 的字段、Web UI 的 JS —— 全是同一套。
