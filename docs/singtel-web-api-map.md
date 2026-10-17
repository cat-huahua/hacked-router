# Singtel/Arcadyan web 界面的字段 ↔ 配置键 映射

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 工具：`webmap.py`
> 目的：把 web UI 里的 `js` 变量翻译成真正的 `ARC_*` 配置键，
> 这样就能**绕过界面直接改配置**（脚本化 / 恢复 / 对比）。

---

## 0. 为什么需要翻译

web 页面的 JS 里不直接写 `ARC_SYS_Password`，而是写数字：

```html
<%ABS_MAP("gateway_id","393231")%>
<%ABS_MAP("lan_mac","131075"+0)%>
addCfg("def_lanip",0,"<% ABS_DFT("131076"+0) %>");
addCfg("ddns_password","ARC_DDNS_"+idx+"_Password", ...);
```

这些数字不是随机的，**是有结构的配置键**：

```
id = (模块号 << 16) | 字段序号

0x6000F (393231) → 模块 6 = ARC_SYS，第 15 项 → ARC_SYS_SerialNum
0x20003 (131075) → 模块 2 = ARC_LAN，第 3 项  → ARC_LAN_x_MACaddr
0x20004 (131076) → ARC_LAN_x_IP4_Addr
0xA000B (655371)→ 模块 10 = ARC_FIREWALL 第 11 项 → ARC_FIREWALL_AC_Enable
```

模块表在 `usr/lib/libarccfg.so` 的 `mod_table`（23 项），
每模块的字段表是 `arc_<模块>_cfg_item_table`，每项 32 字节：

```
[0] 名字指针     "ARC_WLAN_24G_SSID_x_ESSID"
[1] 格式串指针   "ARC_WLAN_24G_SSID_%d_ESSID"
[2] 索引上限
…
```

`webmap.py` 就是把这两张表读出来做翻译。

---

## 1. 四种宏

| 宏 | 含义 |
|---|---|
| `ABS_MAP("var","<id>")` | 单个字段：JS 变量 ↔ 配置项 |
| `ABS_ARR("var","<id>")` | 数组/多实例字段（`%d` 由 JS 的下标补上） |
| `ABS_DFT("<id>")` | 读出该项的**出厂默认值** |
| `addCfg("var","ARC_KEY",value)` | 直接写键名（DDNS、VPN 这类动态拼接的字段） |

服务端（`httpd`）在返回页面前把这些宏替换成真实的 `getVal(...)` / `setVal(...)`。

---

## 2. 工具用法

```bash
# 需要 rootfs（里面有 www/ 和 usr/lib/libarccfg.so）
python3 webmap.py /path/to/rootfs

# 导出 TSV
python3 webmap.py /path/to/rootfs -o webmap.tsv

# 只列 www 里直接出现的 ARC 键
python3 webmap.py /path/to/rootfs --keys
```

输出示例：

```
文件                  宏        JS 变量        数字ID   ARC 键（模板）
cgi/cgi_ac.js         ABS_MAP   acc_enable     0xA000B  ARC_FIREWALL_AC_Enable
cgi/cgi_backhaul.js   ABS_ARR   wl0_wpa_key    0x300F0  ARC_WLAN_24G_STA_SSID_x_WPA_Passphrase
cgi/cgi_apn.js        ABS_MAP   user_password  0xD0085  ARC_USB_DONGLE_Password
cgi/cgi_l2tpd.js      ABS_MAP   l2tpd_pskkey   0xF0032  ARC_L2TP_SERVER_IPSecPSK
```

实测（这一版固件）：

```
414 条映射 · 332 个不同的 ARC 键 · 56 个文件
ABS_MAP 146 · ABS_ARR 253 · addCfg 12 · ABS_DFT 3
其中凭据类（password / passphrase / PSK / WEP key）34 条
```

---

## 3. 典型映射（节选）

| web 变量 | ARC 键 | 说明 |
|---|---|---|
| `gateway_id` | `ARC_SYS_SerialNum` | 设备序列号 |
| `lan_mac` | `ARC_LAN_x_MACaddr` | LAN MAC |
| `lan_ip` | `ARC_LAN_x_IP4_Addr` | LAN IP |
| `def_http_en` | `ARC_SYS_HTTP_Enable` | HTTP 开关 |
| `fire_enable` | `ARC_FIREWALL_Enable` | 防火墙总开关 |
| `acc_enable` | `ARC_FIREWALL_AC_Enable` | 访问控制开关 |
| `def_lanip` | `ARC_LAN_x_IP4_Addr` | LAN IP 的出厂值 |
| `def_http_en` | `ARC_SYS_HTTP_Enable` | HTTP 的出厂值 |
| `wl0_ssid` | `ARC_WLAN_24G_SSID_x_ESSID` | 2.4G SSID |
| `wl0_wpa_key` | `ARC_WLAN_24G_SSID_x_WPA_Passphrase` | 2.4G 口令 |
| `wl0_sta_wpa_key` | `ARC_WLAN_24G_STA_SSID_x_WPA_Passphrase` | 回传 STA 口令 |
| `wl0_wep_key` | `ARC_WLAN_24G_SSID_x_WEP_Key_y` | WEP key（多槽） |
| `apn` | `ARC_USB_DONGLE_Apn` | LTE APN |
| `user_password` | `ARC_USB_DONGLE_Password` | 3G/4G 拨号口令 |
| `ddns_password` | `ARC_DDNS_<n>_Password` | DDNS 口令 |
| `ipsec_auth_pskkey` | `ARC_IPSEC_x_PSK_KEY` | IPsec PSK |
| `l2tpd_pskkey` | `ARC_L2TP_SERVER_IPSecPSK` | L2TP 服务器 PSK |
| `l2tpd_pass` | `ARC_L2TP_SERVER_x_Password_y` | L2TP 账号口令 |
| `pptp_vpnclient_password` | `ARC_VPN_PPTP_CLIENT_x_Password` | PPTP 客户端口令 |
| `ovpn_pwd` | `ARC_VPN_OVPN_CLIENT_x_Password` | OpenVPN 口令 |
| `bt_en` | `ARC_USB_BT_Enable` | Transmission 开关 |
| `bittrt_folder` | `ARC_USB_BT_ShareDirPath` | BT 下载目录 |
| `backhaul_band` | `ARC_WBD_BHband` | mesh 回传频段 |
| `mesh_en` / `blanket_en` | `ARC_WBD_Mode` | mesh / 全屋覆盖模式 |

> 带 `%d`/`y` 的是**模板**：实际键要由 JS 里的数组下标补全。
> 例如 `ARC_WLAN_24G_SSID_x_ESSID` + 下标 0 → `ARC_WLAN_24G_SSID_0_ESSID`。

---

## 4. 写路径：从表单到 flash

```
浏览器表单
  ↓ POST upload.cgi / topolog.cgi
httpd（CGI 处理函数）
  ↓ arc_cfg_set / mapi_ccfg_set_str
mng（内存中的配置树）
  ↓ mngcli commit / arccfg commit
pricfg 分区（.config.tgz）
```

所以：

- **web 改的任何字段，都能用 `mng_cli set <ARC_KEY>=<value>` 复现**；
- 反过来，`mng_cli get <ARC_KEY>` 能读出 web 上的一切（包括口令）；
- 有些动作（改密码、syncwificonfig）不直接改字段，而是走专用 CGI —
  见 [README 的「管理密码为什么改不了」](../README.md)。

---

## 5. 怎么用这张表

### 5.1 脚本化一个界面设置

```bash
# 例子：把 2.4G 口令改掉（不经过 web）
mng_cli set ARC_WLAN_24G_SSID_0_WPA_Passphrase='新口令'
mng_cli commit
```

### 5.2 对比两份配置

```bash
python3 webmap.py rootfs -o webmap.tsv
# 把 webmap.tsv 里的 ARC 键拿去和 .glbcfg 对照，就知道哪些字段有界面、
# 哪些是“隐藏字段”（只能通过 API/TR069 改）
```

### 5.3 找隐藏开关

`.glbcfg` 有 2361 个字段，但 web 只映射了 332 个。
**剩下的 2000 多个字段没有界面入口** —— 其中就包括
`ARC_TELNETD_ENABLE`、`ARC_SSHD_*`、`ARC_3rd_EmbedUR_Enable`、
`ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType` 这些“后台开关”。

---

## 6. 安全观察

1. **口令字段和普通字段走同一条路**：`arc_cfg_set` 不做任何加密，
   明文躺在 `.glbcfg` 和 `pricfg` 分区里。
2. **前端不校验权限**：能登录 admin 就能改所有字段；
   没有“只读账号”之类的细分。
3. **34 个凭据类映射**覆盖了 WiFi、APN、DDNS、IPsec、L2TP、PPTP、OpenVPN、BT ——
   也就是说这些口令**都能从配置里直接读出来**（如果拿到 rootfs/flash backup）。
4. **数字 ID 不是安全边界**：它只是配置表的索引，没有任何鉴权含义。

---

## 7. 证据与限制

- 映射来源：`www/cgi/*.js` 的 `ABS_MAP` / `ABS_ARR` / `addCfg` 宏
- 数字 ID → 键名：`usr/lib/libarccfg.so` 的 `mod_table` 与 `arc_*_cfg_item_table`
- 已知限制：
  - `addCfg` 的第二个参数有两种形态（键名 / 数字），工具只翻译键名形态；
  - 少数 ID 超出字段表范围时显示为 `?`（固件里确实存在“空槽”）；
  - 模板里的 `%d` 需要结合具体页面下标才能变成完整键名。

---

## 8. 一句话

**web 界面只是 `ARC_*` 配置表的一层皮。** 拿到 rootfs 后，
`webmap.py` 能把这层皮完整撕下来 —— 412 条映射、332 个键，
剩下的 2000 多个字段才是这台设备真正的“后台”。
