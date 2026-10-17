# 从 rootfs / 备份文件 / flash dump 里恢复配置

> 目标设备：**Singtel Mesh Router（Arcadyan WG9116AEAC23-ST，v5.02.00 build09b，
> BCM963138）**。方法对同代 Arcadyan 机型基本通用，但**备份加密口令是这台固件里的**，
> 换机型要先按第 3 节的办法确认。
>
> 本文所有结论都来自固件本体（rootfs + `httpd` 反汇编），不是猜的。
> **唯一没做的一步**：没有拿真机上「导出备份」得到的 `Settings.CFG` 做端到端验证
> （见 3.5 的说明）—— 算法链路是完整的，但如实标注。

---

## 0. 一句话结论

这块板子的配置有**四个存放位置**，恢复难度从低到高：

| 你手上有什么 | 能拿到什么 | 需要什么 |
|---|---|---|
| **官方 web 备份 `Settings.CFG`** | **完整配置（含所有口令）** | ★ 一条 `openssl` 命令，**口令写死在固件里** |
| 解包后的 rootfs | 出厂配置包 206 个文件 + 口令文件 + 4 把私钥 | 固件镜像 |
| SPI flash dump | `pricfg` 分区里的 `.config.tgz` + `/data` 里的 `passwd` | CH341A |
| 设备 shell | `mng_cli backup` 直接导出 | root |

★ **最有用的一条**：web 备份是 **`aes-256-cbc` + 全机型固定口令 `xf8V3zOa`**，
加密口令**不在设备里、也不是一机一密** —— 拿到文件就能离线解开，设备不在身边也行。

---

## 1. 四层配置结构（先把地图画清楚）

```
┌─ UBIFS rootfs（只读）────────────────────────────────────────────┐
│  /usr/share/config/etc/          206 个文件的【出厂配置包】        │
│      ├─ passwd                   admin 的 $1$ 哈希                │
│      ├─ config/.glbcfg           2361 个字段的出厂值              │
│      ├─ config/glbcfg.dft        同上（默认值模板）               │
│      ├─ config/glbcfg.fix        升级时要保留的字段清单            │
│      ├─ config/glbcfg.sme        SME / 非 SME 固件切换时要重置的字段│
│      ├─ config/nvram.txt         Broadcom 板级 NVRAM（MAC 等）     │
│      ├─ config/cert/             RootCA + WebServer 私钥（★未加密）│
│      ├─ config/samba / openvpn / dhcp / dropbear …               │
│      └─ samba/smbpasswd          空文件                           │
└──────────────────────────────────────────────────────────────────┘
          │ 开机时 /sbin/sysup（ELF，字符串可见）：
          │   cp -af /usr/share/config/etc/* /etc
          │   ln -sf /data/passwd /etc/passwd
          │   arccfg checkout
          ▼
┌─ tmpfs：/etc = /tmp/etc（每次开机重建）──────────────────────────┐
│  /etc/config/.glbcfg     运行时配置（mng_cli 读写）               │
│  /etc/config/*           dnsmasq / samba / openvpn / …           │
└──────────────────────────────────────────────────────────────────┘
          │ mngcli commit / arccfg commit
          ▼
┌─ MTD 分区 pricfg（名字来自 /etc/glbpartition-name.conf = "pricfg"）┐
│  /etc/config/.glbcfg.tgz    当前完整配置（tar.gz）                │
│  /etc/.config.tgz           同上（arccfg 自己的副本）             │
│  arccfg checkout 开机把它们解回 /etc/config                       │
└──────────────────────────────────────────────────────────────────┘
          │
┌─ MTD 分区 data（JFFS2，挂 /data）────────────────────────────────┐
│  /data/passwd            持久化的口令文件（开机被链接成 /etc/passwd）│
│  /data/dhcpd.leases      租约                                   │
└──────────────────────────────────────────────────────────────────┘
```

**证据（都能在 rootfs 里直接 `strings` 到）：**

```
$ strings sbin/sysup | grep -E 'usr/share|data/passwd|arccfg'
cp -af /usr/share/config/etc/* /etc
ln -sf /data/passwd /etc/passwd
arccfg checkout

$ strings sbin/preinit | grep -E 'data|passwd|tmpfs'
/data   jffs2   mtd:data
cp -f /usr/share/config/etc/passwd /data/passwd
tmpfs /tmp/etc /tmp/var …

$ strings sbin/arccfg | grep -E 'tgz|checkout|commit|mtderase'
/etc/config/.glbcfg.tgz
/etc/.config.tgz
mtd_erase_blk / mtd_safe_write
checkout / commit
cp -af /tmp/.config/. /etc/config; rm -rf /tmp/.config/
```

所以：

- **出厂配置**在 rootfs（`usr/share/config/etc`）
- **用户配置**在 `pricfg` 分区（`/etc/config` 的 tar.gz）
- **用户口令文件**在 `data` 分区（JFFS2）

---

## 2. rootfs 里到底有什么（实测清单）

用 §6 的 `cfgpack.py rootfs <目录>` 一条命令列全。以下是这台 v5.02.00 的实际情况。

### 2.1 账号

`usr/share/config/etc/passwd`：

```
root:!:0:0:root:/:/bin/ash
admin:$1$LzO.ToaL$5imIcbz0deL8NG8YUfde81:0:0:Administrator:/:/bin/sh
ftp:*:55:55:ftp:/home/ftp:/bin/false
network:*:101:101:network:/var:/bin/false
nobody:*:65534:65534:nobody:/var:/bin/false
daemon:*:65534:*:…:/var:/bin/false
```

- `root` 是 **`!`（锁定）** —— 没有 root 口令，SSH/telnet 的 root 登录靠的是
  运行时 `passwd admin` 设的那个口令 + `arc_sshd`/`arc_telnetd` 的开关。
- `admin` 用 **MD5-crypt（`$1$`）**，盐 `LzO.ToaL`。
  ★ 这个哈希**不是** `admin`（`openssl passwd -1 -salt LzO.ToaL admin` 对不上），
  说明它是**出厂参考机的口令**。要还原就按 §2.4 的派生规则算，或者直接破这个 `$1$`。
  **仓库里不贴这个哈希的可破解材料** —— 用工具从你自己的 rootfs 里读。

### 2.2 四把无口令保护的 RSA 私钥

```
usr/share/config/etc/config/cert/RootCA/rootca.key.pem     1679 B
usr/share/config/etc/config/cert/WebServer/webserver.key.pem 1679 B
usr/sbin/key.pem                                           1675 B
usr/lib/server.key                                         1675 B
```

全部是 `-----BEGIN RSA PRIVATE KEY-----`（**没有 `Proc-Type: 4,ENCRYPTED`**），
包括 **RootCA 的私钥**。含义和 DSL-AC87VG 那台一样：同厂设备的 HTTPS 证书
可以被这份材料签出来。

### 2.3 服务侧的“默认不安全”

| 文件 | 出厂状态 |
|---|---|
| `config/samba` | `guest_ok yes`、`guest_account root`、`homes 1`、8 个 USB 共享 `0777` |
| `config/settings.json` | Transmission：`rpc-authentication-required=false`、`rpc-whitelist-enabled=false`、`rpc-bind 0.0.0.0:9091` |
| `config/dropbear` | `PasswordAuth on`、`RootPasswordAuth on`、22 端口 |
| `ppp/options.pptpd` | `require-mschap-v2`，但 `name "pptp-server"`、无额外口令文件 |
| `xl2tpd/xl2tpd.conf` | `access control = no` |
| `config/miniupnpd.conf` / `upnpd` | UPnP 默认开 |

这些不是漏洞本身，但**恢复出厂后如果不改，等于把 USB 盘和 BT 客户端敞开**。
恢复配置时顺手检查一遍。

### 2.4 出厂口令与派生规则（复述，详见主文档）

| 字段 | 出厂值 |
|---|---|
| `ARC_SYS_Password` | `admin`（明文存 glbcfg） |
| `ARC_TR69_Username` / `Password` | `singtel` / `singtel` |
| backhaul / fronthaul PSK | `12345678` |
| WPS PIN | `12345670` |
| `ARC_UI_WEB_REMOTEMN_Password` | 32 位 MD5 字符串 |

运行时会被 `arc_board` 的板级数据覆盖：

```
root/SSH 密码 = "s1ngt3l" + 序列号后 6 位
ARC_ROOT_Passwd            = MD5(它)
ARC_UI_WEB_REMOTEMN_Password = MD5(序列号)
GUI 密码 / WiFi 口令 / WPS PIN = arc_board get gui-pwd / wifi-*-pwd / wps-pin
```

（板级数据在 `/dev/brcmboard`；完整证明链见
[arcadyan-singtel-config-format.md](arcadyan-singtel-config-format.md)。）

---

## 3. ★ web 备份 `Settings.CFG`：完全离线可解

### 3.1 它是怎么生成的

`httpd`（`Singtel-MeshRG_httpd.arm`）里 **`get_backup_name`** / **`mapi_ccfg_backup`**
这条路径会把下面几条命令原样 `system()` 出去。反汇编地址和字符串都能对上：

```
0x4F6E8  mkdir -p /tmp/.config; cp -a /etc/config/ /tmp/.config
0x4F720  mv %s /tmp/.config/config/.glbcfg        ← 先把实时配置导出成明文 .glbcfg
0x4F744  tar czf /tmp/.config.tgz -C /tmp/.config/ .
0x4F770  openssl enc -%s -salt -a -in /tmp/.config.tgz -out /tmp/.config.enc -k %s
0x4F7BC  mv /tmp/.config.enc /tmp/%s
0x4F804  mv /tmp/%s /tmp/httpOnly/                ← 浏览器就是下载这个
0x4F6BC  Settings.CFG                             ← %s 的值，也就是下载文件名
```

反汇编里两个 `%s` 的来源（`httpd` vaddr）：

```
0x35254   movw r3, 0x75dc   ; movt r3, 4      → 0x475DC（默认值 "0"）
0x35260   mov r3, 0x11      ; 取 17 字节
0x35268   movw r1, 0x0047   ; movt r1, 0x0f   → 配置键 0xF0047
0x35274   bl arc_cfg_get
0x35278   movw r3, 0xdc70   ; movt r3, 4      → 0x4DC70 = "xf8V3zOa"（-k 参数）
0x35288   movw r2, 0xf770   ; movt r2, 4      → 上面的 openssl 格式串
0x35298   bl snprintf
0x352A0   bl system
```

### 3.2 `0xF0047` 是什么

`libarccfg.so.0.1` 里 `mod_table`（23 项）和每模块的 `*_cfg_item_table`（每项 32 字节）
把数字键映射成字段名：

```
key = (模块号 << 16) | 字段序号
0xF0047 → 模块 0x0F（ARC_PROJ）第 0x47 项
        → ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType
```

而 `.glbcfg` / `glbcfg.dft` 里这个字段的出厂值是：

```
ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType=aes-256-cbc
```

### 3.3 完整格式

```
文件名   Settings.CFG
内容     OpenSSL「加盐 + base64」文本，开头是 "U2FsdGVkX1"（= "Salted__"）
算法     aes-256-cbc
口令     xf8V3zOa        ← 固件写死，全机型通用
KDF      EVP_BytesToKey，摘要 = MD5   ★ 见下
明文     gzip tar（根下是 config/，内含 .glbcfg / glbcfg.fix / 服务配置）
```

### 3.4 ★ 必须加 `-md md5`

路由器上的 `openssl` 是 **1.0.1t**（镜像里 `strings usr/bin/openssl` 可见），
`openssl enc -k` 的默认 KDF 摘要那时是 **MD5**。

现代 OpenSSL 3.x 把默认改成了 **SHA-256** —— 同样的口令会解出
`bad decrypt`（或垃圾），**这是最容易误判成“密钥不对”的地方**：

```bash
# ✗ 现代默认（SHA-256）
openssl enc -d -aes-256-cbc -salt -a -k xf8V3zOa -in Settings.CFG -out x.tgz
# → bad decrypt

# ✓ 显式 MD5
openssl enc -d -aes-256-cbc -md md5 -salt -a -k xf8V3zOa -in Settings.CFG -out x.tgz
tar tzf x.tgz
# config/.glbcfg
# config/glbcfg.fix
# …
```

已用合成样本做过往返验证（打包 → 解密 → 内容逐字节一致），
并实测了「默认 SHA-256 失败 / `-md md5` 成功」这一对现象。

### 3.5 如实说明：没做真机端到端

算法链路的每一环都有固件证据（命令串、配置键映射、出厂 cipher 值），
但**没有拿真机导出的 `Settings.CFG` 跑过**。如果某台设备解不开，按顺序检查：

1. 文件头是不是 `U2FsdGVkX1`（是 openssl 的 `-a -salt` 格式）
2. 设备上 `mng_cli get ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType` 的值（可能不是 aes-256-cbc）
3. 固件版本（更老的可能是 `des3`）

### 3.6 安全结论

**备份文件的机密性只依赖一个写死的口令。** 文件一旦离开设备（邮件、网盘、售后、
旧电脑），任何拿到本仓库/固件的人都能解开里面的全部口令、WiFi PSK、TR-069 账号。
这不是“一机一密”，也不是“只有厂商能解”。

---

## 4. 从 SPI flash dump 里恢复

拿到整片 flash（`spi-flash-dump-guide.md`）后，配置在两处：

### 4.1 `pricfg` 分区

- 名字来自 `/etc/glbpartition-name.conf`，内容就三个字符：`pricfg`
- `arccfg commit` 把 `/etc/config` 打成 `.config.tgz` 写进去
- 分区里可能有**多个历史版本**（原地写、不擦整块时）—— 逐个 gzip 流扫

```bash
# 方法一：用本仓库的 carve（扫所有 gzip 流，校验 tar + 找 .glbcfg）
python3 cfgpack.py carve flash.bin -o carved

# 方法二：先看分区表，再只切 pricfg
python3 flashdump.py flash.bin
```

### 4.2 `data` 分区（JFFS2）

- `/data/passwd`（持久化口令文件）
- `/data/dhcpd.leases`

```bash
python3 jffs2_extract.py data-partition.bin -o data-out
cat data-out/passwd
```

### 4.3 注意

- `pricfg` 里的 tar.gz 是**明文**（没有走 web 备份那层 openssl），所以
  **flash dump 拿到 = 配置全拿**，不需要任何口令。
- 如果 `arccfg` 用了原地覆盖，旧块里可能残留更早的配置 —— carve 会把它们都列出来，
  按时间/内容挑。

---

## 5. 写回 / 恢复

| 手段 | 做法 | 前提 |
|---|---|---|
| **web 恢复** | 系统 → 备份/恢复 → 恢复，上传 `Settings.CFG` | admin 口令；表单是 `upload.cgi` + `cmd=SYS_PROF` |
| **设备 shell** | `mng_cli backup /tmp/x` / `mng_cli restore /tmp/x` | root |
| **直接写分区** | `arccfg commit`（把 `/etc/config` 写回 pricfg） | root |
| **恢复出厂** | `arc_restore_defaults` → `mng_cli default`（同时删 dhcp 租约） | root |
| **口令文件** | `cp 你的passwd /data/passwd`（或改完 `passwd admin` 后它自己会持久化） | root |

`restore.htm` 里能直接看到表单定义：

```html
<form enctype="multipart/form-data" method="post" action="upload.cgi">
  … cmd:"SYS_PROF" …
  <input type="file" name="restore">
```

`httpd` 侧对应的就是 `mapi_ccfg_restore`，反汇编里的恢复命令是：

```
0x4DC30  openssl enc -%s -salt -d -a -in %s -out /tmp/.config.tgz -k %s
0x4DC70  xf8V3zOa
         tar xzf /tmp/.config.tgz -C /tmp/.config
         cp -af /tmp/.config/config/. /etc/config
```

---

## 6. 工具：`cfgpack.py`

```bash
# ① 分析解包后的 rootfs：配置包、口令文件、私钥、服务侧配置
python3 cfgpack.py rootfs /path/to/rootfs

# ② 解析 .glbcfg：模块统计 + 所有凭据类字段（198 个，空值=出厂未设）
python3 cfgpack.py glbcfg .glbcfg
python3 cfgpack.py glbcfg .glbcfg -o fields.tsv      # 导出全表

# ③ 解密官方 web 备份（自动用 aes-256-cbc + -md md5 + 固定口令）
python3 cfgpack.py decrypt Settings.CFG -o cfg-out

# ④ 反过来：把配置目录打成可上传的 Settings.CFG
python3 cfgpack.py pack cfg-out/config -o Settings.CFG

# ⑤ 从 flash dump 里捞配置 tar.gz
python3 cfgpack.py carve flash.bin -o carved
```

`decrypt` 与 `pack` 已经做过往返自测（见 §3.4）。
`carve` 用「随机数据 + tar.gz + 随机数据」的伪镜像测试通过。

---

## 7. 字段总览（这台固件的 `.glbcfg`）

**2361 个字段，29 个模块：**

| 模块 | 字段数 | 模块 | 字段数 |
|---|---:|---|---:|
| WLAN | 635 | SYS | 65 |
| WAN | 335 | TR69 | 33 |
| VPN | 312 | IP6 | 28 |
| QOS | 265 | OWL | 27 |
| NAT | 134 | UI | 22 |
| ROUTE | 102 | UPNP | 16 |
| IPSEC | 87 | L2TP | 14 |
| LAN | 85 | SPDSVC | 13 |
| USB | 81 | DDNS | 8 |
| FIREWALL | 71 | ALG / IGMP / SSHD / WBD | 5 / 3 / 3 / 3 |

凭据类字段（名字含 `passw`/`pwd`/`psk`/`secret`/`passphrase`/`token`/`username`/
`account`/`wep_key`/`_PIN` 或结尾 `_KEY`）共 **198 个**。其中出厂就有值的：
`ARC_SYS_Password`、`ARC_TR69_Username/Password`、`ARC_WLAN_*_WPA_Passphrase`、
`ARC_UI_WEB_REMOTEMN_Password`。其余（PPPoE、DDNS、IPsec PSK、USB 账号、VPN）
出厂为空，**恢复时最有价值的就是这些“用户后来填进去”的字段**。

---

## 8. 证据地址速查

`httpd`（基址 0x10000，`.rodata` 文件偏移 = vaddr - 0x10000）：

| vaddr | 内容 |
|---|---|
| `0x4F6BC` | `Settings.CFG` |
| `0x4F6E8` | `mkdir -p /tmp/.config; cp -a /etc/config/ /tmp/.config` |
| `0x4F744` | `tar czf /tmp/.config.tgz -C /tmp/.config/ .` |
| `0x4F770` | `openssl enc -%s -salt -a -in … -k %s`（备份） |
| `0x4DC30` | `openssl enc -%s -salt -d -a -in … -k %s`（恢复） |
| `0x4DC70` | `xf8V3zOa` |
| `0x35254`–`0x352A0` | 备份函数：取 `0xF0047` → 拼 openssl → `system()` |

`libarccfg.so.0.1`（`mod_table` @0x3D0F4，23 项；`arc_proj_cfg_item_table` @0x4B81C，
第 71 项 = `ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType`）。

---

## 9. 一句话运维建议

1. **导出过备份文件就别乱传** —— 它是可解的。
2. 恢复出厂后第一件事：改 GUI 口令、WiFi PSK、关掉不用的 Samba guest / Transmission RPC / UPnP。
3. 换机/送修前，先 `cfgpack.py decrypt` 留一份明文配置，比备份文件可靠。
