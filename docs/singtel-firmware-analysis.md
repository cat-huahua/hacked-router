# Singtel Mesh Extender（Arcadyan WE410443-ST v6.02.00）固件分析

2026-10-14 / 15 实测。**结论先行：官方固件是签名 + 加密的，rootfs 解不开；
bootloader 压根不在固件包里。**

## 官方固件直链

```
https://cdn.aws.singtel.com/files/WE410443-ST_v6.02.00_build14_sign_version_new.trx
https://cdn.aws.singtel.com/files/Singtel-MeshRG_v5.02.00_build09b_20230607_sign.w
```

Singtel 的固件页是 JS 渲染的，**直链藏在内嵌 JSON 里**（用 curl 抓 HTML 再
`html.unescape` 之后 regex 挖）。页面路径规律：

```
https://www.singtel.com/personal/support/broadband/how-to-download-latest-firmware/<型号名>
   Singtel-Mesh-Extender   ✓ 存在
   Singtel-Mesh-Router     ✓ 存在
```

CDN 是 S3，**不能列目录**（`AccessDenied`），其它文件名一律 403。
**文件名大小写敏感**：`.zip` 小写能下，`.ZIP` 是 404。

Extender 那份 md5 = `779039f2bb11da0d2f24b7ebcf200c17`（两次下载校验一致）。

## 容器格式

```c
offset  0: magic        0x5d436f74   ("]Cot")
offset  4: 总长度
offset  8: 校验
offset 12: 0x00010000
offset 16: 内核偏移     (0x1c)
offset 20: rootfs 偏移  (0x2d001c)
offset 24: 0
offset 28: uImage 魔数  0x27051956
```

**★ 这个容器格式是公开的** —— OpenWrt 源码里的
`target/linux/ramips/image/mt7621.mk`：

```make
KERNEL := ... | uImage none | arcadyan-trx 0x746f435d
```

`0x746f435d` 的小端字节就是 `5d 43 6f 74`。**但那个工具只加头，不做加密。**

## 加密地图（精确到块）

```
0x000000  0x2b0000  熵 8.00   内核（LZMA）
0x2b0000  0x2c0000  熵 3.45   明文结构
0x2c0000  0x2d0000  熵 0.00   全 0 填充
0x2d0000  0xde0000  熵 8.00   ★ rootfs 数据
0xde0000  0xdf0000  熵 1.98   签名块（末尾 67462 字节）
0xdf0000  末尾      熵 0.04   全 0 填充
```

**⚠️ 熵 8.00 ≠ 加密**（LZMA 压出来也是 8.00）。要靠"能不能解开"区分：

| 区域 | 结论 | 依据 |
|---|---|---|
| 内核（~2.7MB） | **只是压缩，没加密** | **成功解开**（7.7MB），能搜到内核字符串、SQUASHFS 报错信息 |
| uImage 头 / SquashFS 超块 / 签名块 | **明文** | 字段解析全正常（`27051956`、`hsqs`、inode 数都对） |
| **rootfs（~11.1MB）** | **★ 加密** | 熵 7.999 + **0 个 xz 魔数** + 5616 种解压参数全失败 |
| **bootloader** | **不在此文件** | `U-Boot`/`Ralink`/`bootdelay`/`bootcmd`/`password` 全 0 命中 |

### 内核怎么解

uImage 头（偏移 0x1c，64 字节）之后的体是 **LZMA**，但用的是**非标准参数**：

```
props byte = 0x6d   →  lc=1, lp=2, pb=2   （标准是 lc=3/lp=0/pb=2）
dict size  = 8 MB                          （也是非标准）
```

Python 直接 `lzma.decompress(body, format=lzma.FORMAT_ALONE)` 就能解成 7.7MB。
内核里的启动参数：

```
console=ttyS1,57600n8 root=/dev/mtdblock5 init=/sbin/preinit rootfstype=squashfs,jffs2
```

### rootfs 为什么解不开

超块**是合法的**（`inodes=1679 block=131072 comp=4`），而且带"压缩器选项"标志
（`flags=0x6c0`）。但：

- 数据区**一个 xz 魔数都没有**（对照：OpenWrt 的同类镜像有 94 个）
- `unsquashfs 4.7.5`、7-Zip 26.00、PySquashfsImage、**自编译的 sasquatch**
  （6 种解压器全试）—— 全失败
- 手写暴力：**LZMA1/LZMA2 × 52 个偏移 × 9 种字典 × 标准/非标准参数 × 3 种 BCJ 滤波器
  = 5616 种组合** —— 全不命中

→ **是加密的，不是压缩参数问题。** 超块是"贴上去的皮"。

## flash 分区布局（来自 OpenWrt 的 `we410443.dts`，32MB NOR）

```
0x000000  192KB   u-boot          ← bootloader，带密码锁
0x030000   64KB   u-boot-env      ← ★ bootloader 环境变量（密码可能在这）
0x040000   64KB   factory         ← 射频校准
0x050000  31.4MB  firmware (= kernel 0x440000 + rootfs 0x1b20000)
0x1fb0000  64KB   glbcfg
0x1fc0000  64KB   config          ← ★ 设置（管理密码、登录锁）在这
0x1fd0000  64KB   glbcfg2
0x1fe0000  64KB   config2
```

**串口**：`ttyS1, 57600 8N1 3.3V`。OpenWrt wiki 说**没有明显的引脚丝印**，要焊线。

## 密码是怎么存的（从同厂 Mesh Router 的可读配置里得到）

| 参数 | 存储 |
|---|---|
| `ARC_SYS_Password`（管理密码） | **明文** |
| `ARC_ROOT_Passwd` | **明文** |
| `ARC_WLAN_*_WPA_Passphrase`（WiFi 密码） | **明文** |
| `ARC_UI_WEB_REMOTEMN_Password` | MD5（唯一一个哈希，且与登录无关） |

**推论**：我们设备的管理密码大概率也是**明文躺在 `config` 分区（0x1fc0000）里** ——
所以 **SPI 转储能直接读出，不需要爆破哈希**。

## 固件为什么刷不了自己的

`/bin/fw_upgrade`（同厂 Router 的 rootfs 里可读）用的是：

```
arca_validateImage()          ← 验签
arca_writeValidatedImageEx()  ← 验过才写
devCtl_setImageState / getBootedImageId        ← Broadcom flash 工具
```

**只接受签名镜像。** 所以"用网线刷自己的代码"这条路，卡在签名上。

## 密码为什么"社区找不到"

OpenWrt 移植者写的是 "bootloader is locked with a password… **currently unknown**"。

但注意：**他们为了装 OpenWrt 必须先用 SPI 把整个 flash 读出来**
—— 那里面就有 `u-boot`(0x0) 和 `u-boot-env`(0x30000)。

> **所以"找不到"的真正含义是：一旦你能读 flash，你就再也不需要那个密码了。**
> 没人有动机去破解它 —— 是"没人去弄"，不是"弄不到"。

另外两种可能：密码是按设备派生的（一份 dump 只对那一台有效）；
或者密码只锁**串口菜单**，而 **Web 恢复模式是另一条独立入口**（见下一篇）。

## 自己动手时的备忘录

```
① 内核  → 能读（LZMA 非标准参数，FORMAT_ALONE 直接解）
② rootfs → 读不了（唯一加密的部分；云端 agent / 网页代码 / 默认配置都在里面）
③ bootloader → 不在这份文件里（在芯片 0x0~0x30000）
```

**越是靠近"操作系统之下"的东西，越是拿不到** —— 这也正是为什么要看
[u-boot 的 Web 恢复模式](uboot-web-recovery.md)。
