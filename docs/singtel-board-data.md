# Singtel Mesh Router 的板级数据（`arc_board`）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/bin/arc_board`、`/dev/brcmboard`、`/sbin/arc_glbcfg`
> 一句话：**一机一密的 GUI 密码、WiFi 口令、WPS PIN 都存在板级数据里，
> 通过 `/dev/brcmboard` 的 ioctl 读写。**

---

## 1. 工具

```sh
arc_board get <key>
arc_board set <key> <value>
```

完整 usage（二进制里原样）：

```
Usage:
  arc_board set|get <basemac|wps-pin|wifi-24g-pwd|wifi-5g-pwd|sn|model|
                      hwver|clone-flag|mptest|ccode|tcode|gpon-sn [hex]|
                      gpon-pwd [hex]|gui-pwd|wifi-bh-pwd|wifi-24g-ssid|
                      wifi-5g-ssid|wifi-bh-ssid|tempboot|vendorcontent1>
```

数据源：`/dev/brcmboard`（Broadcom 板级 NVRAM），`arc_board` 通过 ioctl 读写，
并用 `crc_getCrc32` 校验。

---

## 2. ★ 键 ↔ NVRAM 名字对照表

| `arc_board` 键 | NVRAM 名字 | 内容 |
|---|---|---|
| `sn` | `arcSerial` | 序列号 |
| `model` | `arcModel` | 型号 |
| `hwver` | `arcHwVer` | 硬件版本 |
| `basemac` | `ucaBaseMacAddr` | 基础 MAC |
| `clone-flag` | `arcCloneFlag` | MAC 克隆标志 |
| `mptest` | `arcMPTest` | 工厂测试 |
| `ccode` | `arcWLANCcode` | 国家码 |
| `tcode` | `arcWLANTcode` | 区域码 |
| **`gui-pwd`** | **`arc_gui_pwd`** | **GUI 管理密码** |
| **`wps-pin`** | **`wpsDevicePin`** | **WPS PIN** |
| **`wifi-24g-pwd`** | **`arcWifi24GPwd`** | **2.4G 口令** |
| **`wifi-5g-pwd`** | **`arcWifi5GPwd`** | **5G 口令** |
| **`wifi-bh-pwd`** | **`arc_wifi_backhaul_pwd`** | **回传口令** |
| `wifi-24g-ssid` | `arc_wifi_24g_ssid` | 2.4G SSID |
| `wifi-5g-ssid` | `arc_wifi_5g_ssid` | 5G SSID |
| `wifi-bh-ssid` | `arc_wifi_backhaul_ssid` | 回传 SSID |
| `dect-rfpi` | `DECTRfpi` | DECT RFPI |
| `gpon-sn` | `gponSerialNumber` | GPON 序列号（hex） |
| **`gpon-pwd`** | **`gponPassword`** | **GPON 口令（hex）** |
| `tempboot` | `arcTempBoot` | 临时启动标志 |
| `vendorcontent1` | — | 厂商自定义 |

---

## 3. 运行时怎么用这些值

`/sbin/arc_glbcfg`（恢复出厂时）会：

```sh
sn=$(arc_board get sn)
gui_pwd=$(arc_board get gui-pwd)
wps_pin=$(arc_board get wps-pin)
wifi_24g_pwd=$(arc_board get wifi-24g-pwd)
wifi_5g_pwd=$(arc_board get wifi-5g-pwd)
wifi_bh_pwd=$(arc_board get wifi-bh-pwd)
```

然后写进 `.glbcfg`：

```
ARC_SYS_SerialNum            = $sn
ARC_SYS_Password             = $gui_pwd
ARC_WLAN_*_WPS_ExRegistrarPIN= $wps_pin
ARC_WLAN_*_WPA_Passphrase    = $wifi_*_pwd
```

所以**板级数据是“一机一密”的源头**：

- 恢复出厂后 GUI 密码 = `arc_gui_pwd`
- WiFi 口令 = `arcWifi*Pwd`
- WPS PIN = `wpsDevicePin`
- 回传口令 = `arc_wifi_backhaul_pwd`

---

## 4. 怎么读

在设备 shell（root）上：

```sh
arc_board get sn
arc_board get model
arc_board get hwver
arc_board get basemac
arc_board get wps-pin
arc_board get wifi-24g-pwd
arc_board get wifi-5g-pwd
arc_board get wifi-bh-pwd
arc_board get gui-pwd
```

> 这些是**明文**返回值；`arc_board` 不做哈希。

也可以直接读 NVRAM（如果 `nvram` 工具可用）：

```sh
nvram get arc_gui_pwd
nvram get arcWifi24GPwd
```

---

## 5. 写入/修改

```sh
arc_board set wifi-24g-pwd 'NewPassphrase'
arc_board set gui-pwd 'NewGuiPassword'
```

限制：

- 长度有校验（错误串里能看到 `must >=%d && <=%d`）；
- `basemac` 必须是 `xx:xx:xx:xx:xx:xx`；
- `gpon-sn` / `gpon-pwd` 是 hex；
- 写入后**不会自动同步到 `.glbcfg`**，需要 `arc_glbcfg` 或手动 `mng_cli set`。

---

## 6. 安全观察

1. **板级数据是明文**：拿到 root/SPI dump 就能读出所有一机一密口令。
2. **`gui-pwd` 是 GUI 密码的真正来源**：不是 `passwd` 里的哈希，
   也不是 SN 派生（SN 只派生出 SSH/root 密码 `s1ngt3l+后6位`）。
3. **`wps-pin` 是 8 位**，如果 WPS 开着（回传默认开），就是可攻击面。
4. **`gpon-pwd`** 是 GPON 认证口令，属于运营商层面的敏感数据。
5. **`arc_board set` 会写板级 NVRAM**，写错可能导致 WiFi/管理口令变化；
   改完记得 `mng_cli set` + `commit` 同步到配置。

---

## 7. 证据索引

| 内容 | 位置 |
|---|---|
| 工具 | `/bin/arc_board`（usage、`/dev/brcmboard`） |
| 键/NVRAM 名 | `arc_board` 字符串（`arcSerial`、`arc_gui_pwd` 等） |
| 运行时覆盖 | `/sbin/arc_glbcfg`（`arc_board get ...`） |
| 板级节点 | `/dev/brcmboard` |
| 配置落点 | `.glbcfg` 的 `ARC_SYS_Password` / `ARC_WLAN_*` |
