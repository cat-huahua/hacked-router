# Arcadyan / Singtel 设备的配置与密码机制

适用：Singtel 发放的 Arcadyan 设备（`WE410443-ST` mesh extender、
`Singtel-MeshRG` / DSL 系列路由器等）。2026-10-16 实测与分析。

## 摘要（先说结论）

| 项 | 结论 |
|---|---|
| **glbcfg 配置** | ★ **纯明文** `key=value`，不需要解密 |
| **密码派生机制** | ★ **已完整破译**（见第 2 节）—— root/SSH 密码是**可算的** |
| **extender 的 rootfs** | 固定byte变换包裹XZ；已完整提取，见[更正与证据](singtel-extender-crypto-path.md) |
| **厂商共用默认物** | 有共用私钥 + 默认账户哈希（见第 6 节） |

---

## 1. glbcfg 是明文的

`glbcfg.dft`（出厂默认配置）是 **ASCII 文本**，2480 行、75422 字节：

```
ARC_WAN_Type=1
ARC_WAN_BaseType=1
ARC_WAN_Active=0 1 2
...
ARC_UI_WEB_REMOTEMN_Password=<32 位 MD5>                          ← MD5(SN)，见下
ARC_TR69_Password=VENDOR_PASSWORD_HERE                                          ← 默认值
```

flash 里的 `glbcfg`(0x1fb0000) / `config`(0x1fc0000) 分区同理 ——
**管理密码、WiFi 口令都是明文躺在里面**，SPI 读出来即可，**不需要爆破哈希**。

## 2. ★ 密码派生机制（从 `/sbin/arc_glbcfg` 读出）

`arc_glbcfg` 是个 **POSIX shell 脚本**（不是二进制），恢复出厂时执行，
里面把每个默认密码怎么来的写得清清楚楚：

```sh
# 默认 SSH 密码 = VENDOR_PREFIX_HERE + 序列号后 6 位
ssh_passwd="VENDOR_PREFIX_HERE`echo $sn | cut -c $(($s_len-5))-`"
echo -e "$ssh_passwd\n$ssh_passwd\n" | passwd admin
mngcli set ARC_ROOT_Passwd=`echo -n "$ssh_passwd" | md5sum | ...`

# 远程管理密码 = MD5(序列号)
mngcli set ARC_UI_WEB_REMOTEMN_Password=`echo -n "$sn" | md5sum | ...`
```

| 东西 | 怎么来的 | 能否离线算出 |
|---|---|---|
| **root / SSH 密码** | `VENDOR_PREFIX_HERE` + **序列号后 6 位** | ★ **能**（只要知道 SN） |
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

同一厂固件的默认账户哈希（模板值，见第 6 节）。用 hashcat 模式 500 +
掩码 `VENDOR_PREFIX_HERE?d?d?d?d?d?d`（100 万候选）**31 秒命中**：

```
命中值 = VENDOR_PREFIX_HERE + 模板设备序列号的后 6 位
```

**代码里读到的派生规则 = 哈希里解出来的真值** —— 两个方向互证，规则钉死。

> 具体的模板哈希与命中口令**不写进仓库**（那是真实设备的默认口令形态）。
> 要看自己的，用 `cfgpack.py rootfs <你的rootfs>` 从固件里读哈希再破。

### 强制改密闸门是怎么回事

httpd 里有这句：

```
[%s] Default password is used, force to change it.
Location: /change_pwd.htm
```

**闸门只拦 `.htm` 页面的跳转，不拦写接口** —— 所以"用出厂密码登录 →
返回 `change_pwd.htm`"其实**已经算登录成功**，之后照样能调 `sync*` 写接口。
这一点在 [singtel-mesh-login-lock.md](singtel-mesh-login-lock.md) 里也有记录。

## 3. extender rootfs：已完整提取（2026-10-24 更正）

旧版根据高熵、AES候选不命中和kernel config推断“key在flash”，该结论错误。
真实路径是 `squashfs_xz_uncompress` 的固定 XOR/rotate → XZ → byte substitution。
完整样本已提取1247 files、98 directories、334 symlinks，无需SPI dump。
详见[算法、地址与提取证据](singtel-extender-crypto-path.md)。
不能对 `+110` 后全部数据统一变换：squashfs索引与未压缩块须由正常reader处理。

## 4. 怎么验证一把 rootfs 密钥（方法论）

如果要试某台设备的 rootfs 密钥，按成本从低到高：

1. **先判断是不是弱变换**：单字节 XOR（256 种）、4 字节块 `rand()` XOR（种子取文件头各字段）、
   重复密钥 XOR（**自相关找周期**）、ECB（**数重复的 16 字节块**）。
2. **再试候选密钥**：厂商名、型号、`VENDOR_PREFIX_HERE`、全零/全 FF、文件头魔数、已知哈希。
3. **拿 AES 试**：ECB 与 CBC（IV=0 / 文件头 IV / 块号），**只看第一个数据块能不能变成合法魔数**。
4. 都不中 → 老老实实承认密钥不在手上。

**不要靠熵**判断加密与否（压缩数据熵也是 8.0）；**不要靠"看起来像随机"**下结论。

## 5. 同厂设备里的 OWL 子系统（与 extender 的 MQTT 云【不是一套】）

同厂另一台设备（`Singtel-MeshRG` / DSL 系列）的 rootfs 是**未加密的 ubifs**，直接可读。
里面有一套完整的 **OWL**（Arcadyan 的 SON / 自组网子系统）：

```
usr/lib/libArcOWLcore.so      438KB  核心（JSON 序列化、RRM/BTM 决策）
usr/lib/libArcOWLapi.so        66KB
usr/lib/libArcOWLhttpApi.so   6.1KB
usr/agents/arca-owl-agent.so
usr/sbin/owl  owl_monitor  owl-tplg  arc_ieee1905_owl
usr/share/config/etc/arcOwl/config.owl
```

`config.owl`（纯文本，类 C 语法）里写着设备身份：

```
DEVICE_INFORMATION {
    MODEL_NAME     ARC-VDSLIAD;
    PRODUCT_ID     VRV9519AAWAC34-A-TA;
    SERIAL_NUMBER  <序列号>;
    ...
}
OWL_DATA_TRANSMISSION_MODE 1;   # 1 = IEEE1905.1, 2 = socket
```

glbcfg 里还露出**云端地址**：

```
ARC_OWL_CLOUD_Enable=0
ARC_OWL_CLOUD_URL=https://stage1.arciot.com:55668      ← ★ 注意 stage1 = 测试环境
```

> **★ 对"extender 的 MQTT 命令格式"这条线有用的判断**：
> 这套 OWL 走的是 **JSON + libmicrohttpd**（HTTP），云端是 **arciot.com**；
> 而 extender 走的是 **MQTT over TLS** 到 `mqtt.wifi-analytics.singtel.com.sg`，
> 负载还是 zlib 压缩的。**两者不是同一套协议** —— 实测这台设备的 rootfs 里
> `wifi-analytics` / `adornment` / `desired_state` / `mqtt` **全部 0 命中**。
>
> 这段只比较当时使用的不同样本，不能证明MQTT只存在于extender。
> 2026-10-24：extender rootfs已从固件完整解出，不需要flash dump，见第3节。

顺带一提：**正式固件里指向 `stage1` 测试环境**，这本身是个工程质量问题
（测试后端可能不具备生产级的安全与容量保障）。

## 6. 厂商共用默认物（★ 有实际意义的安全发现）

从同厂某台设备的官方固件里解出的 rootfs 中（**未加密部分**）实测到：

- **`admin` 账户自带一个 MD5-crypt 默认哈希**（模板值）→ 说明默认口令是**全设备族共用**的，
  不是每台现算的。**已破解**（模式 500 + `VENDOR_PREFIX_HERE?d?d?d?d?d?d` 掩码，31 秒）→ 见第 2 节。
- **两张未加密的共用 RSA 私钥**（`server.key` / `key.pem`，2048 位，无 `Proc-Type: ENCRYPTED` 头）。
  **厂商全设备共用同一把私钥** = 这些设备的 TLS 身份不具备唯一性。
- **自签证书的 CN 直接写成 `www.singtel.com`**（有效期 2021–2031）；
  另一张证书的 issuer 是 **`telus`**（加拿大运营商）、CN 是 `TS-Mesh-WLAN.home` ——
  **厂商从别家运营商的项目复制模板**留下的痕迹。
- 设备**不校验**服务端证书 —— 这正是[冒充云端](singtel-firmware-analysis.md)能成功的原因。

---

# ★ 附：配置字段全表与其中的安全相关项

## glbcfg 的规模与分组（实测 2361 个字段）

```
ARC_WLAN   635    ARC_WAN    335    ARC_VPN    312    ARC_QOS    265
ARC_NAT    134    ARC_ROUTE  102    ARC_IPSEC   87    ARC_LAN     85
ARC_USB     81    ARC_FIREWALL 71   ARC_SYS     65    ARC_TR69    33
ARC_IP      28    ARC_OWL     27    ARC_UI      22    ARC_UPNP    16
ARC_L      14     ARC_SPDSVC  13    ARC_DDNS     8    ARC_ALG      5
```

## ★ ARC_OWL_*（27 个）—— SON / 漫游参数 + 云端账号

```
ARC_OWL_MAIN_LOOP_TIME=60        ARC_OWL_SON_DELAY_TIME=1
ARC_OWL_ROAMING_SIGNAL=-70       ARC_OWL_ROAMING_SIGNAL_BTM=-65
ARC_OWL_OverLoad_2G=70           ARC_OWL_OverLoad_5G=70
ARC_OWL_THRESH_2G=-55            ARC_OWL_THRESH_5G=-80
ARC_OWL_Rssi_Low=-70             ARC_OWL_Rssi_Low_BTM=-65
ARC_OWL_Thresh_Diff=8            ARC_OWL_Thresh_Diff_BTM=10
ARC_OWL_steer_capability=3       ARC_OWL_steer_Default=1
ARC_OWL_Steer_prohibit=300       ARC_OWL_AutoEnableBandSteering=1
ARC_OWL_Active_Period=10         ARC_OWL_Active_Thresh_Count=10
ARC_OWL_acl_expire_t0/t1/t2 = 60 / 1200 / 3600
ARC_OWL_BlackList_expire=3600    ARC_OWL_BTM_BlackList_expire=3600
ARC_OWL_ChanLoad_Report_t=60

★ ARC_OWL_CLOUD_ENABLE=0
★ ARC_OWL_CLOUD_URL=https://stage1.arciot.com:55668      ← 【测试环境】
★ ARC_OWL_CLOUD_USER=mg-test@arciot.com                 ← 【一个测试账号】
```

> **两件事**：① 出厂配置里带的是一个 **`mg-test@` 测试账号**、指向 **stage1** 测试云；
> ② 这套参数说明 OWL 的判据是**信号强度 + 信道负载 + BTM（802.11v 的 BSS Transition
> Management）**，`Thresh_Diff=8` 意思是"目标 AP 比当前强 8dB 才触发漫游"。

## ★ ARC_UI_WEB_REMOTEMN_* —— 出厂配置里带 **Singtel 的公网 IP 白名单**

```
ARC_UI_WEB_REMOTEMN_Enable = 0          ← 默认关着
ARC_UI_WEB_REMOTEMN_Https  = 0
ARC_UI_WEB_REMOTEMN_Port   = 8080
ARC_UI_WEB_REMOTEMN_ExposeToIP_0 = 165.21.21.38  ~  165.21.21.40
ARC_UI_WEB_REMOTEMN_ExposeToIP_1 = 203.125.232.138
ARC_UI_WEB_REMOTEMN_ExposeToIP_2..7 = 0.0.0.0 ~ 0.0.0.0
ARC_UI_WEB_REMOTEMN_ExposeToAny = 0
```

**出厂就预置了 Singtel 自己的公网网段**（`165.21.x` 与 `203.125.x` 是 Singtel 的地址空间），
供其运维从外部访问设备 Web 界面（默认 `Enable=0`，但白名单是**预置好的**）。
⇒ 只要有人把 `Enable` 打开（或某个云端策略把它打开），这台设备的管理界面就会对
**上面那几个公网 IP** 开放 8080 端口。**这是设备所有者应该知道的一条。**

## ★ ARC_SYS_* 里的出厂值

```
ARC_SYS_LoginName=admin      ARC_SYS_Password=admin        ← 出厂默认（明文！）
ARC_SYS_LoginEnable=1        ARC_SYS_RouterDisable=0
ARC_SYS_HTTP_Enable=1        ARC_SYS_HTTPS_Enable=1        ARC_SYS_HTTP_UseSpecialPort=0
ARC_SYS_TimeZone=SGT-8
ARC_SYS_NTP_SERVER_0=ntp5.singnet.com.sg
ARC_SYS_NTP_SERVER_1=ntp6.singnet.com.sg
ARC_SYS_NTP_SyncInterval=3600
ARC_SYS_StopDnsRebind=1      ARC_SYS_MultiWAN_DNS_Enable=1
ARC_SYS_LogType=ilog  ARC_SYS_LOG_Level=info  ARC_SYS_LogDumping=0
ARC_SYS_LOG_RemoteEnable=0  ARC_SYS_LOG_RemoteServerAddr=0.0.0.0  Port=514
ARC_SYS_PPPOEPassthru=1      ARC_SYS_MACCLONE_Enable=0
```

## ★ WPS / WEP 的出厂状态

```
ARC_WLAN_*_SSID_*_WPS_ExRegistrarPIN = VENDOR_WPS_PIN_HERE      ← 所有 SSID 同一个出厂 WPS PIN
ARC_WLAN_24G_WPS_PINEnable = 0                        ← WPS PIN 默认关
ARC_WLAN_*_WEP_KeyType = hex   WEP_DftKeyId = 1   WEP_KeyLen = 0
ARC_WLAN_*_SSID_*_WPA_GroupRekey = 0
ARC_USB_DONGLE_PinState=-1  PinLock=0  PinTimes=3     ← 3G/4G 上网卡 SIM 的 PIN 状态
```

## 三家厂商的「配置里存了什么」对照

| | NETGEAR R7800（1213 字段） | Singtel glbcfg（2361 字段） | 华为 Q2S |
|---|---|---|---|
| 管理密码 | `http_passwd` = **SHA256** | `ARC_SYS_Password` = **明文** | `http_passwd` = **SHA256(MD5())** |
| WiFi 口令 | `wl_wpa2_psk` = **明文** | `ARC_WLAN_*_WPA_Passphrase` = **明文** | 未知（加密） |
| 系统账户 | `dhx2_passwd` = MD5-crypt | 无（只用 `admin`） | 未知 |
| Samba | `samba_passwd` = **NTLM** | 无 | 无 |
| 安全问题答案 | `PWD_answer1/2` = SHA256 | 无此机制 | 无 |
| PPPoE | `wan_pppoe_*`（出厂 `guest`/`flets`） | `ARC_WAN_*_PPP_*` | 未知 |
| 云端账号 | ReadyCLOUD（运行时下载 agent） | `ARC_OWL_CLOUD_USER=mg-test@...` | 未知 |
| TR-069 | `cwmp_*` | `ARC_TR69_Password=VENDOR_PASSWORD_HERE` | 未知 |
| 远程管理白名单 | — | **预置 Singtel 公网 IP** | — |
| 弱口令检查 | `weak_password_check=0` | — | — |

## 7. 安全发现（负责任披露）

同厂固件里存在**工厂/诊断类 CGI 入口**，可在设备上读出板级数据（含 `gui-pwd`、
`wps-pin`、WiFi 口令这类出厂密钥）。若这类入口在**鉴权之前**可达，即为信息泄漏缺陷。

> **具体端点名与参数此处不公开**，以免成为对仍在网设备的一键利用配方。
> 详细记录保存在本地（不进仓库）。建议：厂商应把工厂/诊断类 CGI 限制为
> **需鉴权 + 仅限出厂网络**；用户在设备退役前应确认其不暴露于 LAN/WAN。

相关：[singtel-firmware-analysis.md](singtel-firmware-analysis.md)（加密地图 / 分区表）·
[singtel-mesh-login-lock.md](singtel-mesh-login-lock.md)（登录锁）·
[huawei-config-format.md](huawei-config-format.md)（另一种设计：密钥在设备上）

## Extender kernel 路径的更正

早期把 file `0x53a878` 当作函数地址，实际是日志字符串。
正确kernel load为 `0x81001000`，wrapper VA为 `0x81134cc0`；
`CONFIG_CRYPTO_ECB=y` 不能证明squashfs调用AES。
完整证据与可复现工具见[extender crypto路径](singtel-extender-crypto-path.md)。

# ★ 附：Arcadyan 的服务架构是「dbus agent 框架」（与 NETGEAR 完全不同）

解出 Singtel Mesh Router 的 rootfs 后，服务架构一目了然 ——
**整台设备只启用了一个 init 服务，其余全是 dbus agent。**

## 启动链

```sh
# /usr/share/config/etc/init.d/arcadyan-agent-loader   （rc.d 里唯一的 S09 链接）
start() {
    # 先等 dbus-daemon 起来
    PIDS=`ps | grep -w "dbus-daemon" | grep -v grep | awk '{print $1}'`
    while [ -z $PIDS ]; do echo "Wait for dbus-daemon starting up ..."; sleep 1; ... done
    /usr/sbin/arca-agent-loader /usr/agents &
}
stop() {
    dbus-arca-cli --notify CMD_QUIT
    killall arca-agent-loader
}
```

**`/etc` 本身是 `-> ./tmp/etc` 的符号链接（tmpfs）** —— 运行时配置从
`/usr/share/config/etc` 复制出来，所以固件里的 `/etc/init.d` 是空的、
真正的服务定义在 `/usr/share/config/etc/init.d` 里。

## 36 个 dbus agent（`/usr/agents/arca-*-agent.so`）

```
ECOmode   autofw     autowandetect  crond     ddns        dhcp6c     dhcp6d
dhcpc     dhcpd      dhcprelay      dnsmasq   ecmh        firewall   httpd
ieee1905  igmpproxysnooping         l2tp      l2tpd       misc       openvpn
owl       pptp       qos            radvd     syslog_ng   tr69       transmission
udevd     ula        upnp           usbapp    v6rd        wanppp     wlan
zebra
```

**⇒ 每一项网络服务（DHCP/DNS/防火墙/VPN/UPnP/TR-069/QoS/无线…）都是一个独立 agent，
通过 dbus 通信。** 这与 NETGEAR R7800 的
「lighttpd + net-cgi 单体」设计是两种完全不同的思路：

| | NETGEAR R7800 | Arcadyan（Mesh Router / DSL） |
|---|---|---|
| Web 服务 | lighttpd + net-cgi | 自家 `httpd`（`Singtel-MeshRG_httpd.arm`） |
| 服务模型 | 传统 init 脚本 + 单体 CGI | **dbus agent 框架**（36 个 .so） |
| 配置 | `/bin/config`（`datalib`） | `mng_cli` / `arc_glbcfg` / glbcfg 文本 |
| 进程管理 | start-stop-daemon | `arca-agent-loader` + `dbus-arca-cli` |

## OWL / ATDP：mesh 层的两个内核模块

`/sbin/arc_ieee1905_owl`（shell 脚本）：

```sh
"boot" | "CMD_BOOT")
    echo "==>Boot ATDP and OWL" > /dev/console
    KERNELVER=`uname -r`
    insmod /lib/modules/$KERNELVER/extra/arc_oshal.ko;
    insmod /lib/modules/$KERNELVER/extra/drv_atdp.ko;
```

- **ATDP = Arcadyan Topology Discovery Protocol**（`drv_atdp.ko` +
  配套的 `arc_atdp_app` / `arc_atdp_util` / `arc_backhaul_handle_atdp_set_owlie_daemon`）
- **OWL** 建在 ATDP 之上（`arca-owl-agent.so` + `libArcOWLcore/api/httpApi.so`）
- 三者关系：**IEEE1905 ↔ ATDP（厂商自己的拓扑发现）→ OWL（SON / 漫游决策）**

> 这也解释了符号表里的发现：**`owl_*` 在 extender 的内核里**
> （`owl_build_beacon_ie` / `owl_insert_tlv`）—— OWL 是**信标 IE 里的 TLV**，
> 属于空口 mesh 协议，与云端 MQTT 是两回事。

## 顺带：`arc_*` 工具集（近 100 个）

```
arc_glbcfg  arc_board  arccfg  arc_cfg_cli  arc_nvram  arc_nvram_sync
arc_wlan  arc_lan  arc_wan  arc_wanmode  arc_wandown  arc_wanup
arc_firewalld  arc_firewall6  arc_qos  arc_vlan  arc_bridge  arc_switch
arc_tr69_trigger  arc_spdsvc  arc_spdsvc_tr69  arc_ddns  arc_ntpclient
arc_telnetd  arc_sshd  arc_reboot  arc_restore_defaults  arc_mt_reset
arc_fw_md5sum  arc_util_cert_gen  arc_ledd  arc_gpiod  arc_iptal …
```
（`arc_telnetd` / `arc_sshd` 说明**开 telnet / SSH 是设备本身具备的能力**，
只是默认不启用。）

---

# ★ 附：Singtel Mesh Router 的 httpd 接口面（21 个 CGI）

从 `Singtel-MeshRG_httpd.arm`（= 固件里的 `/usr/sbin/httpd`，md5 `78479f6c…`）提取：

```
apply_abstract_cgi        apply_cgi                 backhaul_cgi
bs_settings_cgi           get_info_cgi              get_topology_clients_cgi
__init_cgi                login_cgi                 logout_cgi
lte_settings_cgi          lte_warn_cgi              owl_cmd_cgi
setpwd_cgi                setpwd2_cgi               singtel_cgi
sw_img_cgi                upload_cgi                upload_torrent_file_cgi
vpnupload_cgi             wl_cal_cgi                （另有一个工厂测试类 CGI，见下）
```

按用途分组：

| 组 | CGI |
|---|---|
| 登录/口令 | `login_cgi` `logout_cgi` `setpwd_cgi` `setpwd2_cgi` |
| 配置 | `apply_cgi` `apply_abstract_cgi` `bs_settings_cgi` `backhaul_cgi` `__init_cgi` |
| 查询 | `get_info_cgi` `get_topology_clients_cgi` `get_info` |
| 固件/上传 | `sw_img_cgi` `upload_cgi` `upload_torrent_file_cgi` `vpnupload_cgi` |
| 无线/校准 | `wl_cal_cgi`（`/wireless_calibration.htm`） |
| LTE | `lte_settings_cgi` `lte_warn_cgi` |
| **OWL / 云** | `owl_cmd_cgi` ← OWL 命令通道 |
| Singtel 定制 | `singtel_cgi` |

## ★ 两套认证并存

`httpd` 里同时有：

1. **HTTP Digest**：

   ```
   Digest realm="Password required to Singtel RG", qop="auth,auth-int",
          nonce="%s", opaque="5ccc069c403ebaf9f0171e9517f40e41"
   ```

   （注意 `opaque` 就是那个 Apache digest 示例常量 `5ccc069c…` —— 早先以为是密钥，是诱饵。）

   `get_nonce_num` 说明 nonce 是个**递增计数**。

2. **httoken**（我们一直在用的那套）：`httoken=` / `httoken` 字段。

**两种都接受** —— 这也解释了为什么不同工具/页面能用不同方式访问。

## 登录锁的配置键也在这里

```
ARC_SYS_LoginBlocked     ← ★ 锁标志（见 singtel-mesh-login-lock.md）
ARC_SYS_LoginEnable
ARC_SYS_LoginName
ARC_SYS_LoginTimeout
```

## 其它

- `/tmp/tr69/Devicetype.xml` —— TR-069 的设备类型描述
- `/cgi/cgi_*.js` 一整套前端接口（`cgi_dev` / `cgi_login` / `cgi_wireless` /
  `cgi_topology_client_cnt` / `cgi_pcm` / `cgi_systime` …）
- 页面：`/login.htm` `/change_pwd.htm` `/setup_top_login.htm` `/loginpserr.htm`
  `/index.htm` `/wireless_calibration.htm` `/lte_warn.htm`
- `httpd` 里**唯一的对外 URL 是 `http://www.apache.org/`** —— 没有云端地址；
  云端对接在 agent / `owl_cmd_cgi` 那一层

> **关于那个工厂测试类 CGI**：它的存在与能力已在
> [本文件第 7 节](#7-安全发现负责任披露)说明过（会明文打印板级口令），
> **此处不列出调用方式** —— 按负责任披露原则保留。

---

# ★★ 附：Arcadyan 的内部 dbus 控制协议（整台设备的总控台）

36 个 agent 之间不是靠文件或信号通信，而是靠 **dbus**。而他们在 `dbus-arca-cli` 里
**把手册都写进用法字符串了** —— 于是我们拿到了这台设备的完整内部 API。

## 1. 44 个 dbus 接口：`arca.dbus.<服务>`

```
autofw  autowandetect  crond  ddns  dhcp6c  dhcp6d  dhcpc  dhcpd  dhcprelay
dnsmasq  ecmh  ECOmode  firewall  httpd  ieee1905  igmpproxy  ipsecvpn
l2tp  l2tpd  misc  openvpn  owl  pptp  qos  radvd  service  syslog_ng  tr69
transmission  udevd  upa/ula  upnp  usbapp  v6rd  wanppp  wlan  zebra
```

**44 个接口 = 44 个可独立控制的服务。** 每个接口都有一套 `CMD_*` 方法 + 可查询的状态变量。

## 2. ★ `dbus-arca-cli` 的语法（原文来自二进制里的 usage 串）

```
Usage: dbus-arca-cli <--enquire | --command | --notify> [--dest=NAME]
                     <VARIABLE[=VALUE] | COMMAND[=ARGUMENT]> { ... }

  # 查状态
  dbus-arca-cli --enquire --dest=arca.dbus.dnsmasq STAT_AGENT

  # 发命令（可以一次打给多个服务）
  dbus-arca-cli --command --dest=arca.dbus.dnsmasq "CMD_SLEEP 3" \
                          --dest=arca.dbus.radvd   "CMD_SLEEP 1"

  # 广播（不带 --dest）
  dbus-arca-cli --notify CMD_QUIT

  # 广播 + 定向
  dbus-arca-cli --notify --dest=arca.dbus.dnsmasq STAT_AGENT \
                        --dest=arca.dbus.radvd   CMD_QUIT
```

三种模式：

| 模式 | 作用 |
|---|---|
| `--enquire` | **读**某个服务的状态变量（如 `STAT_AGENT`） |
| `--command` | **下命令**（带参数），可一次给多个服务 |
| `--notify` | **发通知/信号**（不带 dest 就是广播） |

## 3. 95 个 `CMD_*` 动作（按用途归类）

```
# 生命周期
CMD_BOOT  CMD_BOOTSTRAP  CMD_REBOOT*  CMD_RESTART  CMD_STOP  CMD_START
CMD_QUIT  CMD_RELOAD  CMD_REINIT  CMD_DEFAULTS  CMD_CLEAR  CMD_SAVE
CMD_SLEEP  CMD_STAGE2  CMD_TRIGGER  CMD_UPDATE  CMD_IFSEQ

# 上网连接
CMD_CONNECT  CMD_DISCONNECT  CMD_RECONNECT  CMD_RELEASE  CMD_RENEW
CMD_DHCPC_RELEASE  CMD_DHCPC_RENEW  CMD_DHCPC_IPTV_UNI_REQUEST/RELEASE
CMD_WRITE_DHCPD_CLIENTS  CMD_DEL_LEASE  CMD_WAN_UPDATE  CMD_WAN_IFUPDATE
CMD_6RD_RESTART  CMD_DSL_MOD  CMD_DSL_INET_NLED_TOGGLE

# VPN（PPTP / L2TP / OpenVPN 各有独立 agent）
CMD_START_PPTP  CMD_STOP_PPTP  CMD_UPDATE_PPTP  CMD_RESTART_PPTP
CMD_START_PPTPD CMD_STOP_PPTPD CMD_UPDATE_PPTPD CMD_UPDATE_PPTPD_CHAP
CMD_START_L2TP  CMD_STOP_L2TP  CMD_UPDATE_L2TP  CMD_UPDATE_L2TPD_CHAP
CMD_START_OVPNC CMD_STOP_OVPNC CMD_UPDATE_OVPNC
CMD_START_OVPND CMD_STOP_OVPND CMD_UPDATE_OVPND CMD_UPDATE_OVPND_PASSWD
CMD_DEL_PPTP  CMD_DEL_L2TP  CMD_DEL_OVPNC

# 桥接
CMD_BRIDGE_RESTART  CMD_BRIDGE_STOP  CMD_BRIDGE_RELEASE

# USB / 共享
CMD_ACTION_UNMOUNT  CMD_ACTION_USB30TO20  CMD_USB_CONNECT
CMD_FTP_START/STOP/RESTART/UPDATE  CMD_LPD_START/STOP/RESTART
CMD_SAMBA_START/STOP/RESTART/UPDATE/IFMODIFY
CMD_MINIDLNA_START/STOP/RESTART   CMD_DLNA_START/STOP/RESTART/RESCAN/UPDATE

# WPS / 无线
CMD_WPS_PUSHBUTTON  CMD_WPS_ENTERPIN  CMD_WPS_CANCEL  CMD_WL_SPEC

# ACS / 账号 / 时间
CMD_ACS_CHANGE  CMD_ACCOUNT_BOOT/RESET/SET  CMD_TIME_CHANGE
CMD_REINIT_PORTMAPPING
```

## 4. 这意味着什么

**这台设备上有一个"单一控制面"** —— 只要能在设备上执行命令
（root/SSH，密码规则见前面「密码派生」那一节），就能用 **一个 CLI** 精确控制
**44 个服务、95 种动作**，而不必去碰任何 Web 接口：

```bash
# 例：把 DNS 服务重启、把 6rd 重开会话、把 WPS 关掉
dbus-arca-cli --command --dest=arca.dbus.dnsmasq "CMD_RESTART" \
                        --dest=arca.dbus.v6rd     "CMD_6RD_RESTART" \
                        --dest=arca.dbus.wlan     "CMD_WPS_CANCEL"
```

> 与 NETGEAR 的对比：R7800 那边要发 **HTTP 请求到 `net-cgi`**（带 Basic Auth / digest），
> 而且 220 个动作散在一个 CGI 里；这边是**一个本地 dbus 调用**，
> 接口按服务切开、语义清楚得多。

---

# ★ 附：OWL / ATDP 的协议分层（mesh 层到底怎么跑）

前面知道 OWL 是内核里的 SON（自组网）子系统。把 `libArcOWL*.so` 和 `libArcShareATDP.so`
的符号捋一遍，层次就清楚了：

## 分层

```
                    应用：漫游决策（band steering / BTM）
                                        │
        ┌───────────────────────────────┴───────────────────────────────┐
        │  OWL（Arcadyan SON）                                          │
        │  参数在 glbcfg 的 ARC_OWL_*（27 个，见前面那一节）             │
        └───────────────────────────────┬───────────────────────────────┘
                                        │  mgmt frame
        ┌───────────────────────────────┴───────────────────────────────┐
        │  IEEE 1905.1                                                  │
        │  libArc1905_tx_owl_mgmt_frame / _rx_owl_mgmt_frame            │
        │  libArc1905_ObtainDeviceId / obtain_device_MAC                │
        │  libArc1905_obtain_owl_tplg_map（拓扑映射）                    │
        │  Ieee1905NeighborNumberOfEntries / 1905id                     │
        └───────────────────────────────┬───────────────────────────────┘
                                        │  内核：drv_atdp.ko + arc_oshal.ko
        ┌───────────────────────────────┴───────────────────────────────┐
        │  ATDP = Arcadyan Topology Discovery Protocol                  │
        │  libArcShareATDP.so                                           │
        │  内核里：owl_build_beacon_ie / owl_insert_tlv（信标 IE 的 TLV）│
        └───────────────────────────────┬───────────────────────────────┘
                                        │  厂商私有消息
        ┌───────────────────────────────┴───────────────────────────────┐
        │  Broadcom 底层能力                                            │
        │  bcm_wifi_get_assoc_list / get_rssi / get_channel_overload    │
        │  bcm_wifi_rrm_enable_disable（802.11k）                       │
        │  chanim_stats（信道干扰统计）· bsd_proc_event（带宽 Steering） │
        └───────────────────────────────────────────────────────────────┘
```

## ★ 厂商私有消息：`wlpvt`，**按 OUI 校验**

`libArcOWLcore.so` 里有一句非常说明问题的校验失败信息：

```
bsd_validate_wlpvt_message: not BRCM OUI
```

- **`wlpvt`** 是一种**厂商私有消息**（WLAN vendor-tagged 报文）
- 它**按 OUI 校验来源** —— "不是 BRCM 的 OUI 就拒收"

⇒ **这些私有报文用的是 Broadcom 的 OUI**，而且校验很直接（比对 OUI）。
这也解释了为什么 OWL 在**同厂设备之间**能互通、在别家设备上无效。

## OWL 的「词汇表」（从 libArcOWLcore 提取的属性/字段名）

```
bssid  bssid_2g  bssid_5g  channel  bandwidth  chanload_report  chanim_stats
active_period  active_tresh  active_backlist_expire  backlist_expire  block_time
check_bandsteer_mac  check_blacklist_mac  check_conn_mac
rssi  assoc_list  ssid  channel_overload  rrm  beacon_ie
add_data_to_tx_list  assign_data_ready_status  add_app_log  all_data
boardcast / broadcast  accept  action  actframe
```

**这套词汇表就是 OWL 报文里能传的东西** —— 客户端的 RSSI、关联列表、各频段的 BSSID、
信道负载、邻居拓扑，以及"要不要把这个 MAC 拉黑/触发漫游"的决策指令。

## 与前面「owl_* 在 extender 内核里」的呼应

extender 的内核符号里有 `owl_build_beacon_ie` / `owl_insert_tlv` / `Set_OWL_*_Proc`，
正好对上这张图的最下面两层 —— **TLV 装在信标 IE 里走空口**。
所以：

> **OWL 是空口协议（信标 IE 的 TLV + IEEE1905 管理帧），不是云端 MQTT。**
> 云端那套（`mqtt.wifi-analytics.singnet.com.sg`）是另一条完全独立的线。

---

# ★ 附：`arc_board` 的完整键表（板级数据的 schema）

前面说过管理密码来自 `arc_board get gui-pwd`。把 `arc_board` 二进制的字符串提出来，
**它的键表就是板级数据（board data）的完整 schema** —— 共 18 个键：

```
# 身份
basemac        sn             model          hwver
ccode          tcode          dect-rfpi
# 出厂口令（★ 这几个就是"读出来"的那几个）
gui-pwd             wifi-24g-pwd   wifi-5g-pwd    wifi-bh-pwd
wps-pin
# 出厂 SSID
wifi-24g-ssid       wifi-5g-ssid   wifi-bh-ssid
# 产线/其它
clone-flag     mptest          tempboot
gpon-sn        gpon-pwd
```

**读取方式**：`arc_board get <键>`，底层读 **`/dev/brcmboard`**
（Broadcom 的板级 NVRAM 设备）—— 也就是说这些值是**产线烧进 flash 的板级区**，
不是从配置里算出来的。

⇒ 这就是为什么 `ARC_SYS_Password` 算不出来却能**读出来**：
它来自板级数据，键名 `gui-pwd`。

> 与 `arc_glbcfg` 里那三条"可离线算"的规则对照：
> | 东西 | 来源 |
> |---|---|
> | root/SSH 密码 = `VENDOR_PREFIX_HERE`+SN后6位 | **算**（`arc_board get sn` 拿到 SN 即可） |
> | `ARC_ROOT_Passwd` = MD5(上面那个) | **算** |
> | `ARC_UI_WEB_REMOTEMN_Password` = MD5(SN) | **算** |
> | `ARC_SYS_Password` = `arc_board get gui-pwd` | **读**（板级区） |
> | WiFi 口令 / WPS PIN | **读**（`wifi-*-pwd` / `wps-pin`） |

## 附带：Mesh Router 的内核模块（108 个，`extra/` 下 25 个）

```
★ Arcadyan 自己的：  arc_netlink.ko  arc_oshal.ko  drv_atdp.ko
Broadcom DSL：        bcm_enet  bcm_ingqos  bcm_usb  bcmmcast  bcmvlan  bdmf
                      chipinfo  dhd  otp  pktflow  pktrunner  pwrmngtd
                      rdpa  rdpa_cmd  rdpa_gpl  rdpa_gpl_ext  rdpa_mw
                      wfd  wl  wlcsm  wlemf  nciTMSkmod
```

- `rdpa*` = Broadcom 的 **RDP 加速器**（数据面卸载）—— 这台是 DSL SoC
- `dhd` / `wl` / `wlcsm` / `wlemf` / `wfd` = Broadcom 无线栈
- **只有三个 `arc_*` 模块** —— 厂商自己的东西主要在**用户态 agent** 里，
  内核只放了 mesh 相关的那三个（正好和前面的 dbus/OWL 架构对上）

---

# ★ 附：httpd 登录逻辑里几个**能改变安全姿态**的开关

从 `Singtel-MeshRG_httpd.arm` 的字符串能直接把登录流程读出来 ——
其中三条是**配置开关，改了就等于改了安全姿态**：

## 1. ★★ `ARC_SYS_LoginEnable = 0` ⇒ **认证全放行**

```
[%s] Login disabled, all pass
```

字面意思：**登录被禁用时，所有请求都通过**。
也就是说这个字段的语义是**反的**——不是"关闭登录功能"，而是"**取消鉴权**"。
（`ARC_SYS_LoginEnable=1` 是默认值，也是正确的。）

## 2. `ARC_HTTPD_JSONAPI_Enable` —— 另一套 JSON API 的开关

```
ARC_HTTPD_JSONAPI_Enable
D_JSONAPI_Enable
```

httpd 里还有一套 **JSON API**（和 `*.cgi` 那套不同），由这个标志控制。
默认没开时用不到；一旦打开就是**多出来一个接口面**。

## 3. 强制改密闸门与 cookie

```
[%s] Default password is used, force to change it.
Location: /change_pwd.htm
login=0&%s%s; Path=/
[%s] new user %s(%s) comes to login, check user and auth
User from %s(%s) authentication fail.
[%s] %s has already granted, pass
[%s] %s login time out, reauth
/tmp/security_log.txt
```

- 会话 cookie 是 `login=0&<...>; Path=/`
- 登录失败/成功都详细记日志（`/tmp/security_log.txt`）—— 这就是
  [登录锁](singtel-mesh-login-lock.md)里的"失败计数"数据来源
- `ARC_SYS_SerialNum` / `ARC_LAN_0_MACaddr` 参与了会话/摘要的计算

## 4. Digest 认证支持 `MD5-sess`

```
Digest 
MD5-sess
%s:%s:%s
%s:%s:%s:%s:%s:%s
```

httpd 同时接受 **`MD5`** 和 **`MD5-sess`** 两种 digest 算法（`MD5-sess` 对每个会话换一次
nonce 派生，比裸 MD5 稍好）。之前找到的 `nonce` 递增计数器正好配套。

> **一条给设备所有者的自查项**：
> 看 `ARC_SYS_LoginEnable` 是不是 `1`。如果是 `0`，
> **这台设备的 Web 界面完全没有鉴权**（只是"登录功能被禁用"这个词听起来像无害的）。

---

# ★ 附：telnet / SSH / 恢复出厂 的实际实现

这几个脚本把"设备怎么被远程进去、怎么被重置"讲得很清楚。

## 1. ★★ telnet 由配置键控制，打开就是**无登录提示的 root shell**

`/sbin/arc_telnetd`（POSIX shell，344 字节，全文）：

```sh
case "$1" in
    "CMD_BOOT" | "CMD_START" | "CMD_RESTART")
        telnetd_enable=`mng_cli get ARC_TELNETD_ENABLE`
        if [ $telnetd_enable = "1" ] ; then
            echo "start telnetd ..."
            /usr/sbin/telnetd -l /bin/sh            # ★ -l /bin/sh
        fi
        ;;
    "CMD_STOP")
        killall telnetd
```

- **`ARC_TELNETD_ENABLE=1` ⇒ `telnetd -l /bin/sh`**
  —— `-l` 指定的是**直接执行 `/bin/sh`**，**不经过 `login` 程序**，
  所以连密码提示都没有（是 root shell，因为 telnetd 以 root 跑）。
- **出厂默认 `ARC_TELNETD_ENABLE=0`**（`glbcfg.dft` 第 882 行）
- 它在 `CMD_BOOT/START/RESTART` 时检查 —— 也就是**每次开机都会重新读这个键**

> **⇒ 只要能让 `ARC_TELNETD_ENABLE=1` 生效并重启，任何能连到 23 端口的人都是 root。**
> 这是设备自带的（不是我们加的）。所有者的自查项：**确认它是 0。**
> 能改这个键的途径有：Web 管理接口（需登录）、`mng_cli`（需 shell）、
> 或把改过的配置写回 config 分区（需物理/刷写）。

## 2. SSH 走 dropbear，host key 是**运行时生成**

```
/sbin/arc_sshd          ELF ARM（链接 libarc-shared.so / libmidcore.so，
                        用 mapi_ccfg_get_str/set_str 读写配置 → 是个配置驱动的开关器）
/usr/sbin/dropbear      dropbear 本体（init.d 用 procd 管，START=50）
/usr/share/config/etc/dropbear/dropbear_{rsa,dss}_host_key   ← ★ 都是 0 字节
```

**host key 文件是 0 字节** ⇒ 每台设备**首次启动时自己生成**，不是厂商共用的默认密钥 ✓
（这一点比前面几台好：NETGEAR/Arcadyan 那边都发现过**未加密的共用私钥**。）

## 3. 恢复出厂：两步

```sh
# /usr/sbin/arc_restore_defaults（92 字节，全文）
#!/bin/sh
if [ -f /data/dhcpd.leases ] ; then rm /data/dhcpd.leases* ; fi
mng_cli default
```

`mng_cli default` 把 glbcfg 恢复成 `glbcfg.dft` 的出厂值。

## 4. ★ `arc_mt_reset`：重跑 `arc_glbcfg`（**重新派生全部口令**）

```sh
# /usr/sbin/arc_mt_reset 的关键几行
arc_glbcfg start 2>&1 1>>/dev/null        # ★ 重跑派生脚本
mngcli set ARC_WAN_100_Iface=eth0.10      # 手工修正几个值
mngcli set ARC_WAN_100_Ifname=eth0.10
mngcli set ARC_WAN_101_Iface=eth0.20
mngcli set ARC_WAN_101_Ifname=eth0.20
mngcli set ARC_WAN_100_MACaddr=`mngcli get ARC_WLAN_MAC`
mngcli set ARC_WLAN_BAND=5
mngcli set ARC_SYS_IsFactoryDefault=1     # ★ 标记"出厂默认"
mngcli commit
```

**这解释了整条恢复出厂链**：
`arc_restore_defaults`（配置回出厂）→ `arc_glbcfg start`（**按板级数据重新派生
root/SSH 密码、`ARC_ROOT_Passwd`、`ARC_UI_WEB_REMOTEMN_Password` 等**）→ `commit`。

所以"恢复出厂后密码是什么"的答案就在这条链里 ——
**root/SSH 密码 = `VENDOR_PREFIX_HERE` + 序列号后 6 位**（可算），**管理密码来自 `gui-pwd`**（读板级区）。

## 5. 重启

```sh
# /usr/sbin/arc_reboot（55 字节，全文）
#!/bin/sh
echo 1 > /proc/sys/blink_diag_led
kill 1
```
（先点亮诊断 LED，再 `kill 1` —— 杀掉 init 触发重启。）

---

# ★ 附：防火墙实现与**出厂姿态**

## 实现（`/sbin/arc_firewalld`，ARM ELF，stripped）

基础策略是**全 ACCEPT**，再用 `LOG_DROP` 链做选择性丢弃：

```
:INPUT   ACCEPT [0:0]
:FORWARD ACCEPT [0:0]
:OUTPUT  ACCEPT [0:0]

-A INPUT   ! -i %s -j LOG_DROP          ← 只允许指定接口进
-A FORWARD -j LOG_DROP                  ← 转发默认丢
-A FORWARD -i %s -j access_control      ← 访问控制按客户端接口挂链
-A ac_rule_%d -p %s -m multiport --dports %s -j url_blocking
-A url_blocking -m webstr --url  "%s" -j LOG_DROP     ← ★ 自定义 webstr 模块做 URL 阻断
-A url_blocking -m webstr --host "%s" -j LOG_DROP
```

- 有个自定义 iptables 扩展 **`webstr`**（按 URL/主机名匹配）
- 端口里出现的：`1701`(L2TP) `1723`(PPTP) `2222` `5190` `8080`

**六组配置键**：

```
ARC_FIREWALL_Enable  /  ARC_FIREWALL_IDS_*（AntiDOS / BlockNetbios / BlockWANPing）
ARC_FIREWALL_AC_*（访问控制，最多 10 条）  /  ARC_FIREWALL_SCH_RULE_*（时间表）
ARC_FIREWALL_MACFILTER_*（MAC 过滤）       /  ARC_FIREWALL_URL_*（URL 阻断）
ARC_FIREWALL_DMZ_*                        /  ARC_FIREWALL_IdentPass / BlockCookie / BlockJAVA / BlockActivex / BlockProxy / BlockLoopback
```

## ★ 出厂默认姿态（`glbcfg.dft` 实测值）

| 项 | 出厂值 | 含义 |
|---|---|---|
| `ARC_FIREWALL_Enable` | `1` | 防火墙开 |
| **`ARC_UPNP_Enable`** | **`0`** | ★ **UPnP 默认关**（很多路由器默认开） |
| `ARC_FIREWALL_DMZ_Enable` | `0` | DMZ 关 |
| `ARC_UI_WEB_REMOTEMN_Enable` | `0` | 远程 Web 管理关 |
| `ARC_TELNETD_ENABLE` | `0` | telnet 关 |
| `ARC_FIREWALL_IDS_BlockNetbios` | `1` | NetBIOS 阻断开 |
| `ARC_SYS_HTTP_Enable` / `HTTPS_Enable` | `1` / `1` | HTTP 80 + HTTPS 都开 |
| **`ARC_FIREWALL_IDS_BlockWANPing`** | **`0`** | ⚠ **WAN 侧 ping 是允许的**（会回 ping） |
| **`ARC_FIREWALL_IDS_AntiDOS`** | **`0`** | ⚠ 抗 DoS 关 |
| `ARC_FIREWALL_MACFILTER_Enable` | `0` | MAC 过滤未启用 |
| `ARC_FIREWALL_AC_Enable` | `0` | 访问控制未启用 |
| `ARC_FIREWALL_BlockCookie/JAVA/Activex/Proxy/Loopback` | 全 `0` | 这些过滤都关 |
| `ARC_UPNP_IGD_Enable` | `1` | UPnP 总开关关着，但 IGD 子项是 1 |

**小结**：出厂姿态整体是**收敛的**（UPnP/DMZ/远程管理/telnet 全关、NetBIOS 阻断开）。
两处可以商量的：**WAN 侧允许 ping**（会暴露设备在线）与**抗 DoS 关闭**。
客户端隔离是关的（见 NETGEAR 那边的同类项，这条两家一样）。

---

# ★ 附：配置系统怎么用（`mng_cli` / `mngcli` 的完整用法）

前面到处出现的 `mng_cli get/set` 就是这个。它的 usage 字符串是原文：

```
Usage:
	mng_cli get  <name>[@<section>]
	mng_cli set  <name>[@<section>]=<value>
	mng_cli test <name>
	mng_cli mget <name_1> <name_2> .. <name_n>
	mng_cli mset <name>=<value> <name>=<value> .. <name>=<value>
```

## 四种访问层次

底下的 `mapi_ccfg_*` API 才是真身：

| 函数族 | 作用 |
|---|---|
| `mapi_ccfg_get_str` / `_set_str` | 读/写单个键 |
| `mapi_ccfg_get_multiple` / `_set_multiple` / `_prefix_get_multiple` | 批量（按前缀）读写 |
| **`mapi_dft_get` / `mapi_ccfg_get_dft_multiple` / `mapi_ccfg_reset_dft`** | **出厂值（dft）** —— 与运行值分开存 |
| **`mapi_tmp_set`** | **临时覆盖层（tmp）** —— 改了但还没提交 |
| **`mapi_ccfg_commit`** | **提交**（把改动落盘） |
| `mapi_ccfg_test_str` / `mapi_ccfg_unset` / `mapi_ccfg_default` | 存在性检验 / 删除 / 全部恢复默认 |

**所以这台设备的配置是「三层」的**：

```
glbcfg.dft（出厂值） ──reset_dft──┐
                                  ├──→ 运行值（RAM） ──commit──→ config 分区（flash）
tmp 覆盖层 ──tmp_set──────────────┘
```

这也解释了 `arc_glbcfg` 脚本里为什么反复出现
`mngcli set "\`mngcli dft_get ARC_WLAN_..._WPA_GroupRekey\`"`
—— **"把出厂值读出来再写回去"**，等于"这一项恢复默认"。

## `@<section>` 的层级语法

`<name>[@<section>]` 里的 section 是**配置树的分区**。这解释了为什么同一个键名
会被多个 WAN/SSID 实例复用（`ARC_WAN_100_*` / `ARC_WAN_101_*` / `..._200_*` …）——
它们其实是同一套 schema 在不同 section 下的实例。

## 另一个入口：`arc_cfg_cli`（索引式，更底层）

```
arc_cfg_get_idx1 / arc_cfg_set_idx1 / arc_cfg_set_long_idx1 / arc_cfg_get_long_idx1
arc_cfg_unset_idx1 / arc_cfg_get_idx_limit / arc_cfg_get_dft_idx1
```

这个走的是**按索引**访问（`idx1`/`idx2`），是给内部代码用的低层接口；
`mng_cli` 是给人用的名字式接口。两者操作的是同一份配置。

> **对设备所有者的意义**：只要有 shell，`mng_cli get ARC_xxx` 就能把任意一项配置读出来
> （包括 `ARC_SYS_Password`），`mng_cli set` + `commit` 就能改。
> 这也正是 `arc_glbcfg` / `arc_mt_reset` 这些脚本干的事。

---

# ★ 附：WAN 上联类型的映射与起机流程

这台设备**一套固件支持四种上联**，靠 `ARC_WAN_Type` / `ARC_WAN_BaseType` 切换：

| 值 | 类型 | 物理接口 | 起机动作 |
|---|---|---|---|
| **0** | ADSL | `nas0` / `nas1` | GPIO3←1，`bcm_xdslctl --mod a` 再 `--mod d`，建 ATM 连接 |
| **1** | **Ethernet** | `eth0` | `rdpa_wan_init.sh` + `ethswctl -c wan -i eth0 -o enable` |
| **2** | VDSL | `ptm0` | GPIO3←1，`bcm_xdslctl --mod a` 再 `--mod v` |
| **3** | **G.Fast** | `ptm0` | **GPIO3←0**，`bcm_xdslctl --mod a` |

**出厂值 `ARC_WAN_Type=1` = Ethernet 上联** ✓（这台是接在光猫后面跑的）

## 三个 WAN 实例

```
ARC_WAN_Active          = 0 1 2      ← 启用了 0/1/2 三个实例
ARC_WAN_DefaultRouteIdx = 0          ← 实例 0 是默认路由
ARC_WAN_IPTVIdx         = 1          ← 实例 1 给 IPTV 用
```

## ADSL 的 ATM 连接是怎么建的（`arc_wanmode` 原文）

```sh
arc_gpioctrl set 3 1                       # ★ GPIO3 选 DSL 模式
bcm_xdslctl configure --mod a ; --mod d    # ADSL

vpi=`mng_cli get VAR_PVC000_VPI`           # ← 注意还是老的 VAR_ 命名
vci=`mng_cli get VAR_PVC000_VCI`
enc=`mng_cli get VAR_PVC000_ENCAPS`
if [ $enc = "LLC" ]; then encap="llcsnap_eth"; else encap="vcmux_eth"; fi

bcm_atmctl operate conn --add 1.$vpi.$vci aal5 $encap 0 0 0
bcm_atmctl operate conn --state 1.$vpi.$vci disable
bcm_atmctl operate conn --addq 1.$vpi.$vci 0 wfq 0
bcm_atmctl operate conn --createnetdev 1.$vpi.$vci $waniface
bcm_atmctl operate conn --state 1.$vpi.$vci enable
start_dsl_link_check
```

**`ENCAPS` 的映射**：`LLC` → `llcsnap_eth`，其它 → `vcmux_eth`。

> 脚本里有一句厂商自己的注释很说明问题：
> `# Fixme, some old code still use VAR_, will fix it later.`
> —— 所以 `VAR_PVC000_*` 这套老命名和 `ARC_*` 新命名**在同一份配置里并存**。

## 其它细节

- **`arc_gpioctrl set 3 <0|1>`**：GPIO 3 是 **DSL 模式的硬件选择**（1=ADSL/VDSL，0=G.Fast）
- `dsl_link_check.sh` 只在 DSL 类型下启动（Ethernet 时 `killall` 掉它）
- `rdpa_wan_init.sh` 是 Ethernet 模式下初始化 Broadcom RDP 加速器数据面的脚本

---

# ★ 附：`ARC_WLAN` 的配置模型（635 个字段怎么来的）

`ARC_WLAN_*` 是最大的一组（635 个）。它不是一堆平铺的键，而是**四个维度的笛卡尔积**：

```
ARC_WLAN_<频段>_<类型>_<索引>_<属性>
  频段： 24G | 5G
  类型： SSID | STA_SSID | FH_SSID | BH_SSID
  索引： 0 | 1 | 2 | 3
  属性： 16 种（见下）
  + 每个接口一套 MACFILTER（最多 10 个 MAC 槽）
```

## 四个"类型"是什么（这是 mesh 设备的典型结构）

| 类型 | 含义 | 用途 |
|---|---|---|
| `SSID_N` | **主 SSID 模板** | 每频段 4 个可广播的用户网络 |
| **`STA_SSID_N`** | ★ **STA（站点）模式** | **作为客户端去连上级** —— 即**回程客户端** |
| **`FH_SSID`** | ★ **Fronthaul（前传）** | 面向客户端的一面 |
| **`BH_SSID`** | ★ **Backhaul（回传）** | mesh 节点之间的上行 |

**⇒ 所以这台设备天生是 mesh 设备**：同一套无线硬件同时挂着
"给用户连的"（FH/SSID）、"连上级的"（STA）、"给子节点连的"（BH）。

## 每个接口的 16 个属性

```
ESSID  Enable  Hide  Mode  Interface            ← 基本
SecurityType  WPA_Cipher  WPA_Passphrase  WPA_GroupRekey   ← WPA
WEP_Key_0  WEP_Key_1  WEP_Key_2  WEP_Key_3      ← ★ WEP 还留 4 个 key 槽
WEP_KeyLen  WEP_KeyType  WEP_DftKeyId
WPS_Enable  WPS_ExRegistrarEnable  WPS_ExRegistrarPIN  WPS_Unconfigured
```

**注意两点**：
1. **WEP 的 4 个 key 槽还在** —— 这套代码是从很老的版本一路改下来的（和前面
   `Fixme, some old code still use VAR_` 那条注释一个味道）
2. `WPS_Unconfigured` 这个字段 —— WPS 的"未配置"状态是**单独存**的，
   说明 `WPS_ExRegistrarPIN` 那个固定 PIN（出厂 `VENDOR_WPS_PIN_HERE`）是有专门处理路径的

## MAC 过滤

```
ARC_WLAN_<频段>_<类型>_<索引>_MACFILTER_Enable
ARC_WLAN_..._MACFILTER_MaxNum
ARC_WLAN_..._MACFILTER_MAC_0 .. MAC_9        ← 每个接口 10 个槽
```

（12 组 × (1 + 1 + 10) —— 与前面 12 个"频段×类型"组合对得上）

## 索引 0~3 的实际用途（从出厂值看）

| 索引 | 出厂 SSID | 说明 |
|---|---|---|
| 0 | `Singtel` / `Singtel_5G` | 主网络 |
| 1 | `24G_SSID_1` / `5G_SSID_1` | 预留 |
| 2 | `24G_SSID_2` / `5G_SSID_2` | 预留 |
| 3 | `24G_SSID_3` / `5G_SSID_3` | 预留 |

（索引 1/2/3 的 SSID 名就是字面上的模板占位，说明出厂只用了索引 0。）

---

# ★ 附：WiFi 配置怎么落到驱动（`/sbin/arc_wlan`，POSIX shell，8.8KB）

**这套 WiFi 不走 `hostapd` / `nl80211`，而是走 Ralink/MediaTek 的 `iwpriv` / `iwconfig`。**
（这也和内核里一大堆 `RTMP*` / `rt_*` 符号对得上。）

## 4 个 SSID 就是 4 个 BSS 接口

```
wlan0       ← SSID 索引 0
wlan0.1     ← 索引 1
wlan0.2     ← 索引 2
wlan0.3     ← 索引 3
```

对每个 BSS 都逐条下发（脚本里是真的这么写的）：

```sh
iwconfig $wlan essid $essid                    # ARC_WLAN_24G_SSID_$1_ESSID
iwpriv   $wlan sHiddenSSID $hidden
iwconfig wlan0 channel $channel                # ARC_WLAN_24G_Channel（0 = auto）
```

## ★ `sNetworkMode` 的取值表（Ralink/MTK 特有，由 `ARC_WLAN_24G_RadioMode` 决定）

| 值 | 协议 |
|---|---|
| **17** | `b` |
| **18** | `g` |
| **19** | `bg` |
| **20** | `n` |
| **22** | `gn` |
| **23** | `bgn` |

（21 缺失 —— 大概是 `g` 的某个变体被跳过了。脚本里对每个值都是
`wlan0` / `wlan0.1` / `wlan0.2` / `wlan0.3` **四条一起下发**。）

## 信道与带宽

```sh
channel   = ARC_WLAN_24G_Channel
bandwidth = ARC_WLAN_24G_ChannelBandwidth
secondary = ARC_WLAN_24G_ExChannelMode      # 决定上下副信道
# channel == 0 → iwconfig wlan0 channel auto
```

## 14 个函数 = WiFi 应用层的全部动作

```
set_wl_essid    set_wl_apmode   set_wl_wep      set_wl_channel
get_eth_mac     set_wl_bssid    wps_sta_pin     wps_pbc
wl_assoclist    wl_assoclist_alive              wl_macfilter
start_single_ssid   wlan_start   wlan_boot
```

- **WPS 两条路都有**：`wps_sta_pin`（STA 模式的 PIN）/ `wps_pbc`（按钮）
- `wl_assoclist` / `wl_assoclist_alive` —— 关联客户端列表（OWL 的 RSSI/漫游决策就吃这个）
- `wl_macfilter` —— 对应前面 `ARC_WLAN_*_MACFILTER_*`
- `set_wl_wep` —— 前面那 4 个 WEP key 槽最终还是会被下发下去

## 一句话总结这条链

```
glbcfg 的 ARC_WLAN_* （配置）
   ↓ mng_cli get
arc_wlan（shell，用 iwconfig/iwpriv 下发）
   ↓
Ralink/MTK 驱动（rt_*/RTMP*，内核里那一堆符号）
   ↓
OWL（读 assoclist / RSSI，做漫游决策）→ 信标 IE 的 TLV 走空口
```

---

# ★ 附：QoS 的实现（`tc` + HFSC，带动自动测速）

`/sbin/arc_qos`（ARM ELF，34KB，stripped）里能直接看到它拼出来的 `tc` 命令：

```c
tc class change dev %s parent 2:1  classid 2:%x   hfsc sc m2 %dkbit ul rate %dkbit
tc class change dev %s parent 2:   classid 2:%x   hfsc sc m2 %dkbit ul rate %dkbit
tc class change dev %s parent 2:%x classid 2:%x   hfsc rt m1 %dkbit d %dms \
                                                       m2 %dkbit ls %dkbit ul rate %dkbit
```

**用的是 `hfsc`（Hierarchical Fair Service Curve）**，挂在 `2:` 这棵树上；
`rt`（real-time）/`ls`（link-share）/`ul rate` 三档一起用 —— 这是标准的
"给语音/视频保底 + 其余按比例分"的做法。

## 接口

```
eth1   ← LAN 侧（内网）
ppp0   ← WAN 侧（PPPoE 拨号后的接口）
```

## ★ 带「自动测速」

函数名很直白：

```
qos_detect_rate   detect_qos_rate   detect_qos_rate_new
qos_get_wan_rate  qos_get_wan_rate_1  qos_get_wan_rate_2
set_ratefile_byicmp    set_ratefile_byicmp_2      ← ★ 用 ICMP 测带宽，写进 ratefile
qos_reinit_htb  qos_lnk_reinit_htb  check_rate_and_do_wan_qos
qos_egress_tm_rate_setting  get_lan_rate  qos_rate_change_dft
htb_prio_fifo_qdisc
```

也就是说**上/下行速率是自动探测出来的**（`ARC_QOS_AutoRateMode`），
所以不需要用户手填带宽。

> 这套和内核里那堆 `act_*` / `cls_*` / `qca-nss-*` 模块（NETGEAR 那边）是两家的不同实现：
> **Arcadyan = 用户态 `arc_qos` 拼 `tc hfsc`；NETGEAR = `uci2streamboost` + `streamboost`**

## 相关配置键

```
ARC_QOS_AutoRateMode           ← 自动测速开关
ARC_QOS_UploadRate / DownloadRate
ARC_QOS_TCLINK_%d_ClassId      ← 每个 tc 链接的 class id
ARC_QOS_TCLINK_%d_UpStreamRate / DownStreamRate
ARC_QOS_TCLINK_MaxNum
ARC_QOS_CLASS_*  ARC_QOS_CLASS_TCPACK     ← ★ 单独给 TCP ACK 一个类别（防止上行被 ACK 挤爆）
ARC_QOS_ADSL_*
```

---

# ★ 附：VLAN 分流（Internet / IPTV 怎么分）

`/sbin/arc_vlan`（POSIX shell，5.8KB）把每个 WAN 实例的 VLAN 子接口建出来：

```sh
wanx_en          = ARC_WAN_${N}_Enable
wanx_base_ifname = ARC_WAN_${N}_BASE_Ifname
wanx_vlan_en     = ARC_WAN_${N}_VLAN_Tagging
wanx_vlan_id     = ARC_WAN_${N}_VLAN_Id
wanx_vlan_pbit   = ARC_WAN_${N}_VLAN_P_Bit

if [ "$wanx_en" != "1" ]; then return; fi          # 实例没启用 → 不建接口
if [ "$bridge_mode" == "1" ] && ...; then return; fi  # AP/桥接模式 → 不建

ifconfig $wanx_base_ifname 0.0.0.0 up
echo 1 > /proc/sys/net/ipv6/conf/$wanx_base_ifname/disable_ipv6

wanx_ifname="${wanx_base_ifname}.${wanx_vlan_id}"   # ★ 就是 eth0.10 这种
```

**子接口命名 = `<物理接口>.<VLAN ID>`**。

## ★ 出厂的三条 WAN（从 glbcfg 读出来的实际值）

| 实例 | 接口 | VLAN | P-Bit | 用途 |
|---|---|---|---|---|
| `ARC_WAN_100` | `eth0` | **10** | 0 | **互联网** |
| `ARC_WAN_101` | `eth0` | **20** | **4** | **IPTV**（★ 优先级 4） |
| `ARC_WAN_102` | `ppp200` | 无 | 0 | PPPoE 直连（不打 VLAN） |

- 与前面的 `ARC_WAN_IPTVIdx=1` 完全对得上 ✓
- **P-Bit 4** 是 802.1p 优先级 —— IPTV 的组播/视频流在交换机上会被优先调度，
  这是运营商 IPTV 的标准做法
- `ARC_WAN_VLAN_Detecting` 这个键在"自动探测 VLAN"模式下会改变行为
  （探测模式下即使桥接模式也建 VLAN）

## 几个相关的开关

```
ARC_WAN_${N}_Enable          ← 实例开关
ARC_WAN_0_BridgeEnable       ← 桥接/AP 模式（此时不建 VLAN 子接口）
ARC_WAN_${N}_IP4_Proto       ← 该实例的上网方式（bridge/dhcp/pppoe/static…）
ARC_WAN_VLAN_Detecting       ← VLAN 自动探测
```

> 顺带：脚本里对**物理接口**先 `disable_ipv6`，再在其上建 VLAN 子接口 ——
> 所以 IPv6 是在**子接口**上做的，物理口本身不跑 IPv6。

---

# ★ 附：VPN 的配置结构（IPsec / PPTP / L2TP / OpenVPN 全都有）

`ARC_VPN_*`（312 字段）+ `ARC_IPSEC_*`（87 字段）合起来，**这台是一台完整的 VPN 网关**。

## 字段分布

```
OVPN   139    PPTP   90    CLIENT   72    SERVER   2    L2TP_*
```

## ★ IPsec（3 条连接，每条 29 个字段）

这是标准的 **IKE 一阶段 + IPSec 二阶段** 架构：

```
# 通用
Enable  ConnName  ConnType  Auth_Method  KeyExchange_Method
IPVer   Tunnel_Mode  WanIfIdx

# 认证
PSK_KEY            ← ★ 预共享密钥（出厂为空）
CERT_FileName      ← 证书文件名（用 CERT 认证时）

# IKE（一阶段）
Ike_Mode  Ike_AuthAlgo  Ike_EncryptAlgo  Ike_DhGroup  Ike_LifeTime

# IPSec（二阶段）
IPSec_AuthAlgo  IPSec_EncryptAlgo  IPSec_DhGroup  IPSec_LifeTime

# 本端 / 对端
Local_Id   Local_IPType  Local_IPAddr  Local_IPPrefixLen
Remote_GatewayAddr  Remote_Id  Remote_IPType  Remote_IPAddr  Remote_IPPrefixLen
```

**出厂值**：`Ike_Mode`/`KeyExchange` 是 `Auto`，`Auth_Method=PSK`，**`PSK_KEY` 为空**
（即 IPsec 连接都是"预置好但没配密钥"的状态）。

## VPN 客户端实例（OVPN / PPTP / L2TP）

每个实例的字段很一致：

```
ARC_VPN_<PROTO>_CLIENT_Enable          ← 总开关
ARC_VPN_<PROTO>_CLIENT_SecurityType    ← 安全类型
ARC_VPN_<PROTO>_CLIENT_IPSecPSK        ← L2TP over IPsec 用的 PSK
ARC_VPN_<PROTO>_CLIENT_<N>_Username
ARC_VPN_<PROTO>_CLIENT_<N>_Password    ← ★ 明文存
ARC_VPN_<PROTO>_CLIENT_<N>_Server_IP
ARC_VPN_<PROTO>_CLIENT_<N>_Remote_IP
ARC_VPN_<PROTO>_CLIENT_<N>_State
```

⇒ 与前面 dbus 那 95 个 `CMD_*` 里的 VPN 动作**一一对应**
（`CMD_START_PPTP` / `CMD_STOP_OVPNC` / `CMD_UPDATE_PPTPD_CHAP` / `CMD_DEL_OVPNC` …）：
**配置在 glbcfg，动作走 `arca.dbus.pptp|ovpn|l2tp`，实现是各自的 agent。**

## 小结论

这台设备的 VPN 面相当厚（4 种协议、多实例、IPsec 站点到站点），
但对家庭用户来说默认全是关的；**拿到 shell 以后 `mng_cli get ARC_VPN_*` 就能把所有
配置（含明文 Password / PSK）读出来**。
