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

## ★ 口令字段分别用什么哈希（哈希模式对照表）

**解出明文之后最容易踩的坑**：这些口令字段**不是同一种哈希**。拿 MD5 去跑
`samba_passwd` 永远不出结果。

| 配置字段 | 算法 | hashcat 模式 |
|---|---|---|
| `http_passwd` / `http_passwd_digest` | **裸 SHA256(明文)**，无盐 | `-m 1400` |
| `dhx2_passwd` | **MD5-crypt**（`$1$` + 盐 + `$`） | `-m 500` |
| `samba_passwd` | **NTLM = MD4(UTF-16LE(明文))** | `-m 1000` |
| `PWD_answer1` / `PWD_answer2` | **裸 SHA256(答案)** | `-m 1400` |
| `wl_wpa2_psk` / `wla_wpa2_psk` | **明文**（不用破） | — |

### 两个反直觉点

1. **`samba_passwd` 不是 MD5。** NETGEAR 的 ReadySHARE 走 Samba，存的是 **NTLM**
   哈希 —— 也就是把明文按 **UTF-16LE** 编码后再算 MD4。
   注意：**`-m 900`（raw MD4 of ASCII）也不对**，编码必须是 UTF-16LE，否则差之毫厘。
2. **`PWD_answer*` 跟管理密码不是同一套。** 实测里 `http_passwd` / `dhx2_passwd` /
   `samba_passwd` 三个字段解出来是**同一个口令**（这家把管理密码、HTTP digest、
   Samba 共用一套），但两个**安全问题答案**用同一批候选（49 万条家庭相关的
   大小写 / leet / 数字后缀 / 拼接变体）**全部未命中** —— 是另外两个字符串。

### ⚠️ 验证多模式时 `--show` 会串味

hashcat 的 potfile 只存 `hash:明文`，**不记录模式**。所以同一个
`--potfile-path` 先跑 `-m 1000` 命中之后，再跑 `-m 900 ... --show`，
会**把 mode 1000 的条目当成自己的结果**打印出来 —— 看起来像"MD4 也命中了"。

**验证不同模式必须各用各的 `--potfile-path`。** 我就是这样差点误报了一次。

### 怎么生成定向字典（比硬啃 rockyou 高效得多）

比起直接上大字典，**先从已经解出来的配置里"反推"口令习惯**更划算。
同一户人家在不同设备/不同年代的口令通常同源，可用的种子：

```
SSID 里的名字（如 "HomeSweetHome" 里的 Home/Sweet）· 家庭成员名（大小写/全拼/缩写）
设备默认的 psk（旧备份里的 wl_wpa2_psk）· wl_ssid_password 之类的数字串
```

再对每个种子派生：**首字母大写 / 全大写 / 全小写**、**数字后缀 0-9999**、
**符号后缀**（`!` `@` `1` `123` `!@#`）、**leet 替换**（`a→4` `o→0` `e→3` `s→5`）、
**名字之间的排列组合**。这样几十万条候选就能覆盖大部分家用口令，
**几十秒跑完**，比 rockyou 快得多。

## 注意

- **不同型号/不同设备族的 magic 可能不同**（同一个 12 字节头结构，magic 不一样）。
  实测：一台设备的三份备份 magic 都是 `0x20131224`；另一台（名字带 Switcher）也是同一个 magic
  但校验不过 —— 说明**同 magic 也可能对应不同设备族的密钥流**，两个 RNG 都要试。
- 参考实现：[`fysac/orbicfg`](https://github.com/fysac/orbicfg)（Go，为 Orbi 写的，但算法是通用的）。
  它源码里还有一张「宣称的 magic ≠ 实际 magic」的覆盖表 —— 有些设备头里写的值是错的。
- 路由器上负责这件事的二进制是 `/bin/datalib`。

---

# ★ 附：官方固件分析（2026-10-16）

**结论：官方固件的 rootfs 完全可解，而且二进制层面证实了本文的加密分析。**

## 固件直链与容器结构

```
https://www.downloads.netgear.com/files/GDC/R7800/R7800-V1.0.2.90.zip   (30 MB)
```

解开 zip 得到一个 `.img`，结构是：

```
偏移 0x0       文本头（明文）
               device:R7800 / version:V1.0.2.90 / region: /
               hd_id:29764958+0+128+512+4x4+4x4+cascade
偏移 0x80      uImage（"Linux-3.4.103" 内核）
偏移 0x220040  第二个 uImage
偏移 0x220080  ★ squashfs 超块（合法、明文）
               inodes=3862  block=262144  comp=4(xz)  flags=0x06c0
偏移 0x666CFD  "CHK" 标记
```

切出 0x220080 之后的部分直接 `unsquashfs -d sq rootfs.sqsh` ——
**成功解出 3245 个文件 / 161 目录 / 456 符号链接**。

## ★ 二进制层面证实了配置加密分析

`/bin/datalib`（负责读写配置的那个二进制，40 KB，ARM ELF，stripped）：

```
$ file bin/datalib
ELF 32-bit LSB executable, ARM, EABI5, dynamically linked,
  interpreter /lib/ld-uClibc.so.0, stripped

$ readelf -sW bin/datalib | grep -E 'srand|rand'
   UND rand        ← ★
   UND srand       ← ★

$ ls -la lib/ld-uClibc*
  ld-uClibc-0.9.33.2.so     ← ★ 就是 uClibc 0.9.33.2
```

**三条独立吻合**：
1. `datalib` 导入 `srand` / `rand` → 印证"用 rand() 生成密钥流"；
2. 链接的是 **uClibc 0.9.33.2** → 印证"要用 uClibc 那一支的 `rand()`（TYPE_3）"，
   这也解释了为什么我们的配置是用 `uclibc` 而不是 `musl` 解开的；
3. `datalib` 里有 `http_passwd` / `samba_passwd` / `wl_wpa2_psk` / `wla_wpa2_psk` 等
   字段名，以及 `/tmp/datalib-bakrst.bin`（备份恢复用的临时文件，正是我们解的那种格式）。

**所以本文开头那套算法不是猜的，是从固件二进制里核对过的。**

## ⚠️ 一个判据上的教训（值得单列）

`unsquashfs` 读这份**健康的** NETGEAR 镜像时会报：

```
xz: error reading stored compressor options from filesystem!
```

**但它照样把 3245 个文件全解出来了。** 所以这条信息**只是无害警告**，
**不能作为"文件系统坏了/被加密了"的依据**。

我早先在分析另一台设备（Singtel extender）的加密 rootfs 时，
**把这条当成了加密的证据之一** —— 是错的，已在
[arcadyan-singtel-config-format.md](arcadyan-singtel-config-format.md) 里更正。

> **判据必须能区分"良性"和"恶性"**，不能只看到一句 error 就下结论。
> 那次真正的硬证据是 `xz uncompress failed with error code 7` +
> `FATAL ERROR: File system corruption detected`（数据块真的解不开），
> 以及"数据区 0 个 XZ 魔数"（对照：这份 NETGEAR 健康镜像有 434 个）。

## ★ 一个很有说服力的对比：同一台设备上「有真加密」和「没加密」

同一个 rootfs 里还有一个 NETGEAR 自家的加密库 `lib/libntgrcrypt.so`（24 KB）：

```
导出的函数：
  ntgrcrypt_sec_part_open / _close / _reset          ← "安全分区"
  run_cmd_cryptsetup_luksformat / luksopen / luksclose / luksstatus
                                                     ← ★ cryptsetup LUKS（真·全盘加密）
  run_cmd_openssl_aes_dec                            ← 走 openssl 的 AES 解密
  interleave_file                                    ← 还有一步交错/混淆
  ntgrcrypt_key_init / ntgrcrypt_key_get_file / key_rm_file
  ntgrcrypt_get_count / add_count / _count_change    ← 变更计数器
```

**也就是说：这台设备上 NETGEAR 有能力用 LUKS + AES + 计数器做真加密 ——
但配置备份偏偏只用 `rand()` XOR。**

这不是"厂商不会加密"，而是**权衡的结果**：配置备份要能被设备自己、
被 TFTP 恢复、被售后工具在资源极少的早期启动阶段读写，
所以选了最轻的方案 —— **代价就是把种子直接写在文件头里**。

**结论没变，但更清楚了**：本文开头那套算法是**设计选择**，不是疏漏的巧合。
反过来说，同一台设备上其他地方（安全分区）用的是 LUKS ——
**所以"某台 NETGEAR 的备份能解"不等于"这台设备的其他东西也能解"**，
要分清楚分析的是哪一层。

---

# ★ 附：`PWD_question1/2` 的编号对应哪两个问题

解密出来的配置里，安全问题只存**编号**（如 `PWD_question1=4`），看编号根本不知道问的是什么。
从官方固件的语言文件里可以拿到完整对照表
（`www/languages-en.js` 与 `www/language/English.js`）：

```
PWD_question1（第一个安全问题的槽位，共 9 个选项）
  1  What was the name of the first NETGEAR product you purchased?
  2  What was the name of the first school you attended?
  3  What is your oldest sister's first name?
  4  What is your oldest brother's first name?
  5  In what city were you born?
  6  What is your grandmother's first name?
  7  What is your grandfather's first name?
  8  In what year (YYYY) did you graduate from high school?
  9  What is the name of your first employer?

PWD_question2（第二个槽位，共 8 个选项）
  1  What is your youngest sister's first name?
  2  What is your youngest brother's first name?
  3  What is your father's middle name?
  4  What is your mother's middle name?
  5  What was the first name of your first manager?
  6  In what city was your mother born?
  7  In what city was your father born?
  8  What is your best friend's first name?
```

**注意两个槽位的选项列表是不同的**（一个 9 项、一个 8 项），
所以 `PWD_question1` 和 `PWD_question2` 的同一个数字代表**不同的问题**。

配套的 CGI 是 `www/securityquestions.cgi`（里面用 `quest1_1..quest1_9` /
`quest2_1..quest2_8` 这些语言变量填充下拉框）。

这样解出来的配置才算**完整**：字段名 → 值 → **值是什么含义**。

---

# ★ 附：R7800 的登录机制（从 rootfs 脚本读出来的）

解出 R7800 的固件 rootfs 后，`bin/login` 和 `usr/sbin/update_user` 把整套认证讲清楚了。
**而且它从"系统怎么用这些哈希"这一侧，独立印证了前面所有破解结果。**

## 1. ★ telnet 密码 = 管理密码（明文），进去就是 root

`/bin/login`（POSIX shell）：

```sh
echo -n "telnet password:"
read telnet_passwd
telnet_passwd_hashed=$(/usr/sbin/hash-data -e "$telnet_passwd")     # ← 算 SHA256
if [ -n "$telnet_passwd_hashed" ]; then telnet_passwd="$telnet_passwd_hashed"; fi
if [ "$telnet_passwd" = "$(/bin/config get http_passwd)" ]; then
    exec /bin/ash --login                                           # ← 直接 root shell
else
    echo "The password is not correct"; exit 0
fi
```

所以：

- **输入的是管理密码本身**（不是哈希），由 `hash-data -e` 转成 SHA256 后与 `http_passwd` 比
  —— 这反证了 `http_passwd = SHA256(明文)` ✓（与前面 hashcat 破出来的映射完全一致）
- **验过就给 `/bin/ash --login`**，即 root shell
- 登录后的提示语也说明了该怎么处理：

  ```
  === IMPORTANT ============================
   Use 'passwd' to set your login password
   this will disable telnet and enable SSH
  ------------------------------------------
  ```

  **即：一旦用 `passwd` 设了密码，telnet 就关掉、SSH 打开。**

## 2. ★ 三个哈希各自的用途（脚本层面确认）

`/usr/sbin/update_user`：

```sh
http_passwd=$($config get http_passwd)
adduser -G admin admin -H ... << EOF
$http_passwd
$http_passwd
EOF
# ★ 系统 admin 的 shadow 密码随后被换成 dhx2_passwd
sed -i "s#<上面那个>#$(/bin/config get dhx2_passwd)#g" /tmp/config/shadow

# ★ samba 的 admin 密码被换成 samba_passwd
sed -i "s#<原值>#:$(/bin/config get samba_passwd):[#g" /etc/samba/smbpasswd
```

| 字段 | 落到哪 | 印证 |
|---|---|---|
| `http_passwd` | 先给 `adduser`，随后被替换 | = **SHA256(明文)**，用于 telnet/web |
| `dhx2_passwd` | **系统 `admin` 用户的 `/etc/shadow`** | = **MD5-crypt** ✓ |
| `samba_passwd` | **`/etc/samba/smbpasswd` 的第 4 字段（NT 哈希位）** | = **NTLM** ✓ |

**这正是前面从密文里破出来的三个映射 —— 现在两边对上了。**

另外 ReadyCLOUD 的云用户口令也被直接写进 smbpasswd 的 NT 哈希字段：

```sh
echo "$username:$id:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX:$userpasswd:[U          ]:LCT-00000001:" >> $SMB_PASSWD_DIR
```

（`XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX` 是 LM 哈希的占位，`$userpasswd` 是 NT 哈希位。）

## 3. 设备身份（rootfs 顶层就是明文小文件）

```
firmware_version   V1.0.2.90
firmware_region    （空）
module_name        R7800
hardware_version   R7800
hw_id              29764958+0+128+512+4x4+4x4+cascade
cloud_version      20161026
```

`hw_id` 与固件 `.img` 文本头里的 `hd_id` 是同一个值 ✓

> **⚠️ 提醒**：`bin/login` 这条路要能连上 telnet 才有用 ——
> 而 telnet 是否在监听取决于固件设置（默认是不开的）。
> 本文只记录机制，不涉及开启方法。

---

# ★ 附二：NETGEAR ReadyCLOUD 的架构（云 agent 是运行时下载的）

从 R7800 的 `sbin/cloud` 解出来的流程 —— 这条解释了**为什么在所有固件分析里都找不到云 agent**：

```
① 下载   /usr/bin/curl  https://updates1.netgear.com/sw-apps/ready-genie-cloud/<ver>/<file>
         （另一处写的是 https://http.fw.updates1.netgear.com/sw-apps/ready-genie-cloud/）
② 校验   /tmp/cloud_md5、".hash"、/usr/bin/md5sum        ← ★ 用的是 MD5
③ 安装   → /opt/rcagent/   （"install ... to R/W filesystem successfully"）
④ 运行   sed '2s/^/source \/etc\/profile\n/' /opt/rcagent/run_server.sh > /tmp/run_server.sh
         /opt/rcagent/run_server.sh
⑤ 凭据   readycloud_user_admin / readycloud_user_password（config 键）
```

## ★ 关键：`/opt/rcagent` 在固件里**不存在**

`find rootfs -path '*rcagent*'` → 无。所以：

> **ReadyCLOUD 的云 agent 不在固件里，是设备联网后自己下载安装的。**

这解释了为什么我们前面在 R7800 的 rootfs 里翻遍也找不到任何云协议实现 ——
它压根不随固件分发。（对照：Singtel 那边的云端 agent 是烧进 rootfs 的，
所以只能从**加密的** extender rootfs 里拿 —— 两条路都被堵上，但原因完全不同。）

## 值得注意的两点

1. **完整性校验是 MD5**，而且 `.hash` 与被校验的文件**来自同一个服务器** ——
   所以它只能防"传输损坏"，**防不了"服务端被替换/投毒"**。
   真正起作用的只有 HTTPS 的传输加密（`curl`，未见证书固定）。
2. **它会把下载来的脚本改写后执行**：给 `run_server.sh` 插入一行 `source /etc/profile`
   再跑到 `/tmp/run_server.sh`。也就是说**这个文件的内容会被当作代码执行**。

> 结论（就事论事，不夸大）：ReadyCLOUD 的信任模型是「相信 updates1.netgear.com」。
> 想核对自家设备有没有开这个功能，看 config 里的 `readycloud_enable` / `readycloud_register`。

## 相关配置键（全部）

```
readycloud_enable        readycloud_register      readycloud_unregister
readycloud_user          readycloud_control       readycloud_status
readycloud_user_admin    readycloud_user_password
（另有 www/js/fxCloud-2.0.js 与 www/debug_cloud.cgi —— 后者是 0 字节的空占位）
```

---

# ★ 附三：R7800 的 Web 栈（lighttpd + net-cgi）与免认证面

## 架构

```
web 服务器   lighttpd            （★ 以 root 身份运行：server.username = "root"）
CGI 分发     net-cgi             （所有 .htm / .cgi 的动作都在这里）
认证         HTTP Basic          （WWW-Authenticate: Basic realm="NETGEAR R7800"）
```

**关于 Basic Auth 与 `http_passwd`**：`net-cgi` 里比对的是 `http_passwd`（SHA256 十六进制）。
也就是说 —— **Basic 认证里"密码"这一项，浏览器发过来的就是那串 SHA256**。
这正好解释了为什么 NETGEAR 把管理密码存成裸 SHA256：**它既是存储值，也是认证值。**

另外 `net-cgi` 里有 `flag_use_passwd_digest` / `http_passwd_backup` /
`soap_login_mac` / `soap_login_agent` / `is_soap_login` —— 说明还有一种"digest 模式"的开关，
以及 SOAP API 侧的登录跟踪（按 MAC/UA）。

## 80 → 443 的强制跳转，以及它的**例外路径**

`etc/lighttpd/lighttpd_https.conf`：

```
$SERVER["socket"] == ":80" {
  $HTTP["remoteip"] !~ "127.0.0.1" {
    $HTTP["url"] !~ "^(/currentsetting\.htm|/soap/server_sa|/soapapi\.cgi|
                      /cgi-bin/genie\.cgi|/sw-apps/internet-check/connection-check.ntgr|
                      /hidden_info\.htm|/connecttest\.txt)" {
      $HTTP["host"] =~ ".*" { url.redirect = ( ".*" => "https://%0$0" ) }
    }
  }
}
```

**上面这份例外清单 = 允许走明文 HTTP 的路径**（其余一律跳 HTTPS）。
其中两条是**不需要登录**的信息页：

| 路径 | 内容 |
|---|---|
| `currentsetting.htm` | 24 字节的模板 `<% current_setting() %>` —— 区域/标签指纹 |
| `hidden_info.htm` | 6080 字节模板，渲染出 **FW 版本、序列号、无线区域、SSID、PassPhrase、信道** 等 |

`hidden_info.htm` 的模板片段（原样）：

```
FW Version : <% cat_file("/firmware_version") %>
Series number : <% get_sn() %>
Wireless Region : <% wireless_region_Eng() %>
2.4G SSID : <% cfg_get_ssid_html("wl_ssid") %>
2.4G PassPhrase : <% passphrase_bg_msg() %>
2.4G Channel : <% wl_channel() %>
```

> **给设备所有者的提醒**：这两页走的是**明文 HTTP 且不要求登录**。
> 也就是说**同一网段里（或任何能到 80 端口的地方）的人都能读到 FW 版本、序列号、SSID**。
> 想知道自家设备实际暴露了什么，直接在浏览器里访问这两个路径即可。

## CGI 动作表里有 `need_login` 标志

`net-cgi` 里有一张 CGI 动作名表，旁边就是 `need_login` / `"Need login!"`。
表里能看到一些有意思的条目：

```
vlan_delete  apply_iptv_edit  disable_vlan_iptv  rae_router  rae_ap
extender_step1/2  edit_devname  hijack_passwd  funjsq_login/forget/register
```

- **`hijack_passwd`** —— 与 `www/BRS_ap_detect_*.html` 里那句
  `hijack_get_timestamp("wl_ssid_password")` 是同一个"hijack（AP 探测）"子系统
- **`funjsq_*`** —— NETGEAR 中国版的**游戏加速插件**（FunJSQ / 迅游），
  脚本在 `/data/funjsq/bin/funjsq.sh`；`need_login` 表里还有一个
  `funjsq_no_need_login` 的标志

## TLS 配置

```
server.port = 443;  ssl.engine = "enable"
ssl.pemfile  = "/tmp/secure/etc/lighttpd/certs/server.pem"
ssl.cipher-list = "EECDH+AESGCM:EDH+AESGCM:AES128+EDH"
```

证书从 `/tmp/secure/...` 读 —— 即**运行时生成/解出来的**，不在 rootfs 里。
（对照：Arcadyan 那几台是把**未加密的共用私钥**直接放在 rootfs 里。）

---

# ★ 附四：R7800 的完整 CGI 动作表（220 个）

`net-cgi` 里有一张按功能分组的动作表。把它们提出来后，这台设备的 **API 面就一目了然**了
（按用途归类，原样保留命名）：

```
# WAN / 上网方式
pptp  l2tp  orange_pppoe  orange_dhcp  mulpppoe_add/addnum/editnum/edit/del
apply_iptv_edit  disable_vlan_iptv  apply_vlan  vlan_add  apply_vlan_add  vlan_edit  apply_vlan_edit  vlan_delete
ipv6_con_type  ipv6_passthrougth  ipv6_auto  ipv6_tunnel  ipv6_fixed  ipv6_dhcp  ipv6_orange  ipv6_pppoe  ipv6_6rd

# ★ 「hijack」= 设置向导的探测/接管流程（AP 模式检测也在这里）
hijack_dhcp  hijack_pppoe  hijack_pptp  hijack_l2tp  hijack_bpa  hijack_static
hijack_orange  hijack_mac_clone  hijack_to  hijack_success  hijack_set_vlan
hijack_set_wireless  hijack_passwd
（`wl_ssid_password` 与 `hijack_get_timestamp()` 也是这套向导的状态值 ——
 **它是个 CGI 动作 + 时间戳，不是"SSID 的口令"**）

# 无线
wlan  bridge_wlan  wlan_adv  wl_ssid_password  wps_pin  stop_wps_status
wlacl_add/editnum/edit/del/apply            （MAC 访问控制）
wireless_schedule_select_to_edi / _delete / _delete_an
wadv_schedule_add/edit (+_an)
adv_wl_ap_mode  wl_bridge_mode  wl_bridge_sectype  wl_bridge_key
wl_bridge_key1..4  wl_key1..4  wl_get_keyno  wl_get_keylength  wl_bridge_key_length
wl_bridge_wep_64_key                         （★ 仍保留 WEP 的 4 个 key 槽）
wifi_ntgr_hidden_channel  wifi_channel_coexist  wl_sectype  wl_bridge_key3/4

# 设备/状态
connect_status  show_statistic  status  welcome  reboot  factory
upg_agree_conditions  full_conditions  edit_devname  rae_router  rae_ap
extender_step1  extender_step2  detect_update  auto_refresh_value  set_dettype
need_login  secure_pwd_remind  asp_judge_guest_user  wizard_pls_wait  change_multi

# 安全 / 访问控制
block_services_add/editnum/edit/del/apply   block_sites  schedule
acc_control_allow/block  apply_acc_control  add_acc  delete_acc  edit_acc
editnum_acc_allow  editnum_acc_block  editnum_connect_device
ipmac  wps_pin  guestpasswd  hijack_mac_clone

# QoS / 流量
qos_editnum  add_qos_adva  edit_qos_adva  add_qos_online  edit_qos_online
add_qos_ether  edit_qos_ether  qos_addmac  edit_qos_mac  add_qos_mac  edit_qos_mac
qos_del  qos_delmac  qos_del_all  apply_qos  apply_prru_qos  qos_editnode
add_qoslist  edit_qoslist  qos_deletenode  apply_streamboost  apply_wmm
select_qos_edit  traffic  traffic_reset  show_traffic_reset

# USB / 共享 / 下载
usb_setting  usb_approved_add/del  sharefolder_creat/edit/delete  disk_remove
file_browser_open  browser_open/close/apply  open_creat_window  open_browser_window
upnp_media  upnp_media_scan  upnp
add_download_item  add_usb_bt_download_item  green_download  enable_green_download
pause_download  start_download  refresh_download  resume_download  remove_download
green_download_fail  change_priority  remove_history  add_download_item  download_email
hdd_download

# 云 / 远程
ddns  ddns_disable  ddns_register  ddns_reset  email  change_language  browser_language
readycloud_unregister  vpn_compress_conf  vpn_update_cert
vpn_client  vpn_client_connect  vpn_client_disconnect

# ★ 游戏加速插件（NETGEAR 中国版 FunJSQ / 迅游）
funjsq_login  funjsq_forget  funjsq_register  funjsq_pay  funjsq_close
open_plugin  close_plugin  reset_plugin  reset_open_plugin
forget_get_verify  register_get_verify  funjsq_no_need_login

# 诊断
basic_ping  debug_info  collect_log  ntp_debug  asic  manual_set_ant
ule_service_ip_add  remove_server  st_router_add/del/editnum/edit
reservation_add/editnum/edit/del  hdd_download  change_conn_status
auto_refresh_value  onfig  var  tatus  rvices_add  unes_allow_control
```

> 最后一行那几个（`onfig`/`var`/`tatus`/`rvices_add`/`unes_allow_control`）是**被截断的**
> —— 因为我是按可读串扫的，前一个字符被并进了别的串。它们的完整名应该是
> `config` / `var` / `status` / `services_add` / `lines_allow_control` 一类。

## 侧面发现：NETGEAR 自己的安全 C 库 `dni_*`

`net-cgi` 的导入表里有整组 `dni_*` 函数：

```
dni_memcpy_s  dni_strlcpy  dni_strlcat  dni_strcmp_s  dni_strcasecmp_s
dni_strcasestr_s  dni_fprintf_s  dni_sprintf_s  dni_strncmp  dni_strdup
dni_atoi  dni_itoa  dni_strstr  dni_fgets
```

这是 NETGEAR 自研的 **"安全 C 函数"** 库（`_s` 后缀 = Annex K 风格带上界检查）。
也就是说他们把常见的 `strcpy/sprintf` 换成了带长度参数的版本 ——
**但这不保证调用处都检查了返回值**（这类"换了函数但没改用法"的漏洞很常见）。
枚举 CGI 动作时如果想找输入处理缺陷，这几个函数是重点。

---

# ★ 附五：R7800 的服务架构（61 个 init 服务 / 187 个内核模块）

## init.d 全部服务

```
acl  atd  avahi-daemon  aws  boot  br-mode  ca-certificates  cron  dbus  ddns
detcable  dni-debug.init  dni-qos  dnsmasq  done  enet  forked-daapd  glboot
guest_dhcp  hd-idle  igmpproxy.init  init6  kcode  lbd  lighttpd  lltd  lvm2
madwifi  net-br  net-br-dhcpc-helper  net-lan  net-scan  net-wan  ntgrcrypt
ntpclient  openvpn  openvpn_check  openvpn_client  opmode  pot  powerctl
qca-nss-drv  qca-nss-ecm  qcmbr  rcS  ripngd  run_afpd  samba  sched_updates
ssid_steering.init  streamboost  sysctl  sysfixtime  sysfs_config  syslogd
sysstat  telnet  tftpd-hpa  traffic_meter  ubus  uci2streamboost  umount
upnp  usb  watchdog  wlan-common  zebra  zzprefix-check_cert_files
```

三个值得单独点出来的：

| 服务 | 是什么 |
|---|---|
| **`telnet`** | ★ telnet **本身就是一个 init 服务** —— 所以"开 telnet"是设备自带能力，只是默认没启 |
| **`ntgrcrypt`** | 那个 LUKS 安全分区（见前面 `libntgrcrypt.so` 的分析） |
| **`aws`** | 启动 `/usr/sbin/aws-iot` —— **AWS IoT 客户端** |

## ★ 整套云栈都是「运行时安装」，固件里没有

这条和前面 ReadyCLOUD 的结论**完全一致**，而且更彻底：

| 组件 | 固件里有没有 | 证据 |
|---|---|---|
| `/usr/sbin/aws-iot` | **没有** | `init.d/aws` 里写 `start() { /usr/sbin/aws-iot; }`，但文件不存在 |
| `/usr/rae.tar.gz` | **没有** | `init.d/aws` 里 `rae_partion=/usr/rae.tar.gz`，文件不存在 |
| `/opt/rcagent/`（ReadyCLOUD） | **没有** | `find rootfs -path '*rcagent*'` → 无 |

但**它们的"壳"都在**：

- `www/rae_*.htm` 一整套 RAE（**Router Analytics Engine**）引导页面：
  `rae_waiting` / `rae_router` / `rae_main` / `rae_learn` / `rae_learn_ap` /
  `rae_extender*` / `rae_bridge_*`
- `init.d/aws` 里的完整逻辑（含 `panic_partion=/dev/mtd9`、
  `RAE_DIR=/tmp/router-analytics`、按 `artmtd -r region` 判断 `PR` 版则关掉 RA）

**结论**：NETGEAR 的做法是 —— **固件只放"壳"（页面 + init 脚本 + 下载器），
真正的云 agent 与数据分析组件在设备联网后从自家服务器取。**
所以对 R7800 做静态固件分析，**永远看不到云协议本体**。

## 内核模块：187 个

```
ath_*（Qualcomm Atheros 无线：ath_dev/ath_hal/ath_dfs/ath_rate_atheros/ath_spectral…）
qca-nss-*（Qualcomm 网络卸载）
NetUSB.ko / GPL_NetUSB.ko（USB over IP，KC_PRINT 那套）
cbc.ko（AES-CBC）· bonding.ko · act_*（流量整形）· cls_*（分类）…
```

## 与 Arcadyan 的架构对比（一台一个思路）

| | NETGEAR R7800 | Arcadyan（Mesh Router / DSL-AC87VG） |
|---|---|---|
| Web | lighttpd(root) + net-cgi 单体 | 自家 httpd（21 个 CGI） |
| 服务 | **61 个传统 init 脚本** | **1 个** `arcadyan-agent-loader` + **36 个 dbus agent** |
| 配置 | `/bin/config`（`datalib`）、nvram | `mng_cli` / `arc_glbcfg` / glbcfg 文本 |
| 云 agent | ★ **运行时下载**（aws-iot / rae / rcagent） | 烧在 rootfs 里（`arca-*` agent） |
| 加密 | 配置 = `rand()` XOR；另有 LUKS 安全分区 | 配置 = 明文 glbcfg；extender rootfs = AES |
