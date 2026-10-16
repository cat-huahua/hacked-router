# Arcadyan / Singtel 设备的配置与密码机制

适用：Singtel 发放的 Arcadyan 设备（`WE410443-ST` mesh extender、
`Singtel-MeshRG` / DSL 系列路由器等）。2026-10-16 实测与分析。

## 摘要（先说结论）

| 项 | 结论 |
|---|---|
| **glbcfg 配置** | ★ **纯明文** `key=value`，不需要解密 |
| **密码派生机制** | ★ **已完整破译**（见第 2 节）—— root/SSH 密码是**可算的** |
| **extender 的 rootfs** | **加密 squashfs**，密钥在 **bootloader**，**没有 flash dump 就解不开** |
| **厂商共用默认物** | 有共用私钥 + 默认账户哈希（见第 5 节） |

---

## 1. glbcfg 是明文的

`glbcfg.dft`（出厂默认配置）是 **ASCII 文本**，2480 行、75422 字节：

```
ARC_WAN_Type=1
ARC_WAN_BaseType=1
ARC_WAN_Active=0 1 2
...
ARC_UI_WEB_REMOTEMN_Password=9df1b182d873117ae8236f3ef8525247     ← MD5(SN)，见下
ARC_TR69_Password=singtel                                          ← 默认值
```

flash 里的 `glbcfg`(0x1fb0000) / `config`(0x1fc0000) 分区同理 ——
**管理密码、WiFi 口令都是明文躺在里面**，SPI 读出来即可，**不需要爆破哈希**。

## 2. ★ 密码派生机制（从 `/sbin/arc_glbcfg` 读出）

`arc_glbcfg` 是个 **POSIX shell 脚本**（不是二进制），恢复出厂时执行，
里面把每个默认密码怎么来的写得清清楚楚：

```sh
# 默认 SSH 密码 = s1ngt3l + 序列号后 6 位
ssh_passwd="s1ngt3l`echo $sn | cut -c $(($s_len-5))-`"
echo -e "$ssh_passwd\n$ssh_passwd\n" | passwd admin
mngcli set ARC_ROOT_Passwd=`echo -n "$ssh_passwd" | md5sum | ...`

# 远程管理密码 = MD5(序列号)
mngcli set ARC_UI_WEB_REMOTEMN_Password=`echo -n "$sn" | md5sum | ...`
```

| 东西 | 怎么来的 | 能否离线算出 |
|---|---|---|
| **root / SSH 密码** | `s1ngt3l` + **序列号后 6 位** | ★ **能**（只要知道 SN） |
| `ARC_ROOT_Passwd` | `MD5(上面那个)` | ★ **能** |
| `ARC_UI_WEB_REMOTEMN_Password` | `MD5(序列号)` | ★ **能** |
| **管理界面密码** `ARC_SYS_Password` | `arc_board get gui-pwd` | ✗ 板级出厂数据 |
| WiFi 口令 / WPS PIN | `arc_board get wifi-*-pwd` / `wps-pin` | ✗ 板级出厂数据 |
| 默认 SSID | `SINGTEL-<序列号或 MAC 后 4 位>` | ★ 能 |

**板级数据存在 `/dev/brcmboard`**（Broadcom 板级 NVRAM），
`arc_board get <键>` 可读，键包括：
`basemac` `sn` `model` `hwver` `wps-pin` `gui-pwd` `wifi-24g-pwd` `wifi-5g-pwd`
`wifi-bh-pwd` `wifi-*-ssid` `ccode` `tcode`。

> **实际意义**：
> - 恢复出厂后 **root/SSH 进得去**（SN 从设备标签或 `arc_board get sn` 一个命令就有）；
> - **管理界面密码算不出来**，但它**能从设备上读出来**（板级数据）；
> - 所以"恢复出厂 → 被强制改密闸门锁在外面"这个困境**是可解的**。

### ★ 这条规则是被实证过的，不只是读代码

同一厂固件的默认账户哈希（模板值，见第 5 节）：

```
admin:$1$LzO.ToaL$5imIcbz0deL8NG8YUfde81
```

hashcat 模式 500 + 掩码 `s1ngt3l?d?d?d?d?d?d`（100 万候选），**31 秒命中**：

```
s1ngt3l160503
```

即 `s1ngt3l` + `160503`（那个模板设备的序列号后 6 位）。
**代码里读到的派生规则 = 哈希里解出来的真值** —— 两个方向互证，规则钉死。

### 强制改密闸门是怎么回事

httpd 里有这句：

```
[%s] Default password is used, force to change it.
Location: /change_pwd.htm
```

**闸门只拦 `.htm` 页面的跳转，不拦写接口** —— 所以"用出厂密码登录 →
返回 `change_pwd.htm`"其实**已经算登录成功**，之后照样能调 `sync*` 写接口。
这一点在 [singtel-mesh-login-lock.md](singtel-mesh-login-lock.md) 里也有记录。

## 3. extender 的 rootfs：加密的 squashfs（附完整证据）

**容器不加密**（`otrx` 生成的普通 TRX，源码里没有任何加密代码）：

```
magic 0x746F435D | len | crc32 | flag | off1(kernel) | off2(rootfs) | off3
```

**内核不加密**（LZMA，非标准参数 `lc=1/lp=2/pb=2`、dict 8MB，`FORMAT_ALONE` 直接解）。

**rootfs 是"半明文"的** —— 超块明文，其后全部加密：

| 偏移（相对 rootfs 起点） | 内容 | 状态 |
|---|---|---|
| +0 | `hsqs` 超块（96 字节） | ★ **明文**（inodes=1679 block=131072 comp=4 flags=0x06c0 bytes_used 全合法） |
| +96 | comp_opts 元数据块 | **已加密** |
| 其后 | 数据块 / inode 表 / 目录表 | **已加密** |

**判断"是加密而不是压缩参数问题"的证据链**（每一条都实测过）：

1. `unsquashfs` 读得出超块，但**紧接着就报**
   `xz: error reading stored compressor options from filesystem!` —— 超块过了，下一块就不过；
2. 数据区**没有任何压缩魔数**（XZ/GZIP/LZ4/ZSTD/BZIP2 全 0 命中）；
3. 熵 7.999（注意：**熵高本身不说明问题**，压缩后的数据也是 8.0，必须靠"能不能解"判断）；
4. 手写暴力 5616 种解压参数组合（LZMA1/LZMA2 × 偏移 × 字典 × 参数 × BCJ）全失败；
5. **不是重复密钥 XOR**：单字节 256 种全试失败；自相关找周期，最大只有 1.4×（自然重复水平）；
6. **不是常见候选密钥的 AES**：41 个候选密钥（厂商名/型号/`s1ngt3l`/全零/全 FF/TRX 魔数/各类哈希）×
   ECB / CBC(IV=0) / CBC(header IV) 全失败。

**密钥在哪**：flash 的 `u-boot`(0x0)–`u-boot-env`(0x30000)。

> **⚠️ 我们手上没有它。** 实测：`Singtel-MeshRG.w`、`ubi_vuln.img`、`ubi_patched.img`
> 里搜 `U-Boot` / `bootdelay` / `bootcmd` **全部 0 命中** —— 那些是运行系统的 UBI 镜像，
> **不含 bootloader**。
>
> **所以：没有 SPI flash 物理读取，这块 rootfs 解不开。** 这不是方法问题，是信息不存在。

对比意义：**NETGEAR 把种子写在文件头里**（所以能解）、**华为把密钥放设备上**（一机一密）、
**Arcadyan 把密钥放 bootloader 里**（最靠下，最难拿）。三种设计的安全强度依次递增。

## 4. 怎么验证一把 rootfs 密钥（方法论）

如果要试某台设备的 rootfs 密钥，按成本从低到高：

1. **先判断是不是弱变换**：单字节 XOR（256 种）、4 字节块 `rand()` XOR（种子取文件头各字段）、
   重复密钥 XOR（**自相关找周期**）、ECB（**数重复的 16 字节块**）。
2. **再试候选密钥**：厂商名、型号、`s1ngt3l`、全零/全 FF、文件头魔数、已知哈希。
3. **拿 AES 试**：ECB 与 CBC（IV=0 / 文件头 IV / 块号），**只看第一个数据块能不能变成合法魔数**。
4. 都不中 → 老老实实承认密钥不在手上。

**不要靠熵**判断加密与否（压缩数据熵也是 8.0）；**不要靠"看起来像随机"**下结论。

## 5. 厂商共用默认物（★ 有实际意义的安全发现）

从同厂某台设备的官方固件里解出的 rootfs 中（**未加密部分**）实测到：

- **`admin` 账户自带一个 MD5-crypt 默认哈希**（模板值）→ 说明默认口令是**全设备族共用**的，
  不是每台现算的。**已破解**（模式 500 + `s1ngt3l?d?d?d?d?d?d` 掩码，31 秒）→ 见第 2 节。
- **两张未加密的共用 RSA 私钥**（`server.key` / `key.pem`，2048 位，无 `Proc-Type: ENCRYPTED` 头）。
  **厂商全设备共用同一把私钥** = 这些设备的 TLS 身份不具备唯一性。
- **自签证书的 CN 直接写成 `www.singtel.com`**（有效期 2021–2031）；
  另一张证书的 issuer 是 **`telus`**（加拿大运营商）、CN 是 `TS-Mesh-WLAN.home` ——
  **厂商从别家运营商的项目复制模板**留下的痕迹。
- 设备**不校验**服务端证书 —— 这正是[冒充云端](singtel-firmware-analysis.md)能成功的原因。

## 6. 安全发现（负责任披露）

同厂固件里存在**工厂/诊断类 CGI 入口**，可在设备上读出板级数据（含 `gui-pwd`、
`wps-pin`、WiFi 口令这类出厂密钥）。若这类入口在**鉴权之前**可达，即为信息泄漏缺陷。

> **具体端点名与参数此处不公开**，以免成为对仍在网设备的一键利用配方。
> 详细记录保存在本地（不进仓库）。建议：厂商应把工厂/诊断类 CGI 限制为
> **需鉴权 + 仅限出厂网络**；用户在设备退役前应确认其不暴露于 LAN/WAN。

相关：[singtel-firmware-analysis.md](singtel-firmware-analysis.md)（加密地图 / 分区表）·
[singtel-mesh-login-lock.md](singtel-mesh-login-lock.md)（登录锁）·
[huawei-config-format.md](huawei-config-format.md)（另一种设计：密钥在设备上）
