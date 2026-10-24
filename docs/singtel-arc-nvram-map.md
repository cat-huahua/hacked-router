# ARC 配置 ↔ Broadcom nvram 映射（`libarc-nvramsync.so`）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/lib/libarc-nvramsync.so.0.1`、`/usr/sbin/arc_nvram_sync`
> 一句话：**`ARC_WLAN_*` 配置最终会被翻译成 `wl0_*` / `wl1_*` 的 Broadcom nvram
> 键，再写进驱动。**

---

## 1. 前缀规则

| 频段 | 基础接口 | VAP |
|---|---|---|
| 2.4G | `wl1` | `wl1.1` / `wl1.2` / `wl1.3` |
| 5G | `wl0` | `wl0.1` / `wl0.2` / `wl0.3` |

nvram 键 = `<前缀>_<后缀>`，例如：

```
ARC_WLAN_24G_SSID_1_ESSID  →  wl1.1_ssid
ARC_WLAN_5G_SSID_0_ESSID   →  wl0_ssid
```

- SSID 0 用基础接口（`wl1` / `wl0`）；
- SSID 1..3 用 VAP（`wl1.1..3` / `wl0.1..3`）；
- `arc_ieee1905_owl` 明确把 `wl0.2` / `wl1.2` 当**回传**（backhaul）。

---

## 2. 从 `.rodata` 暴力配对出来的映射

`libarc-nvramsync.so` 的 `.rodata` 里，`ARC_*` 键后面紧跟 nvram 后缀。
自动扫描（44 对，去掉明显的相邻噪声）后，确认的对应关系：

### 2.1 每 SSID

| ARC 键（模板） | nvram 后缀 |
|---|---|
| `ARC_WLAN_%s_SSID_%d_ESSID` | `ssid` |
| `ARC_WLAN_%s_SSID_%d_Hide` | `closed` |
| `ARC_WLAN_%s_SSID_%d_Enable` | `bss_enabled` |
| `ARC_WLAN_%s_SSID_%d_AP_Isolated` | `ap_isolate` |
| `ARC_WLAN_%s_IGMP_Snooping` | `wmf_bss_enable` |
| `ARC_WLAN_%s_SSID_%d_SecurityType` | 决定 `wep` / `wpa` / `wpa2` / `psk` / `psk2` / `disabled` |
| `ARC_WLAN_%s_SSID_%d_WPA_Passphrase` | `wpa_psk` |
| `ARC_WLAN_%s_SSID_%d_WPA_Cipher` | `crypto`（`tkip` / `ccmp` / `tkip+ccmp`） |
| `ARC_WLAN_%s_SSID_%d_WPA_GroupRekey` | `wpa_gtk_rekey` |
| `ARC_WLAN_%s_SSID_%d_WEP_DftKeyId` | `wep`（默认 key 号） |
| `ARC_WLAN_%s_SSID_%d_WEP_Key_0..3` | `key1`..`key4` |
| `ARC_WLAN_%s_SSID_%d_MACFILTER_Enable` | `macmode` |
| `ARC_WLAN_%s_MACFILTER_Action` | `macmode`（allow/deny） |
| `ARC_WLAN_%s_MACFILTER_MAC_%d` | `maclist` |

### 2.2 每射频

| ARC 键 | nvram 后缀 |
|---|---|
| `ARC_WLAN_%s_Channel` | `chanspec` |
| `ARC_WLAN_%s_ChannelBandwidth` | `bw_cap` |
| `ARC_WLAN_%s_CountryCode` | `country_code` |
| `ARC_WLAN_%s_CountryRev` | `country_rev` |
| `ARC_WLAN_%s_NONLY` | `nreqd` |
| `ARC_WLAN_%s_Coex` | `obss_coex` |
| `ARC_WLAN_%s_Protection` | `nmode_protection` |
| `ARC_WLAN_%s_WMM_Enable` | `wme` |
| `ARC_WLAN_%s_WMM_NoACK` | `wme_no_ack` |
| `ARC_WLAN_%s_WMM_APSD` | `wme_apsd` |
| `ARC_WLAN_%s_DTIM` | `dtim` |
| `ARC_WLAN_%s_Beacon_Int` | `bcn` |
| `ARC_WLAN_%s_Tx_Burst` | `frameburst` |
| `ARC_WLAN_%s_Air_Fairness` | `atf` |
| `ARC_WLAN_%s_BF_Imp` | `mu_features` |
| `ARC_WLAN_%s_BF_Exp` | `txbf_bfr_cap` / `txbf_bfe_cap` |
| `ARC_WLAN_%s_TxBFEnable` | `txbf_imp` |
| `ARC_WLAN_%s_MRate` | `mrate`（固定速率表） |
| `ARC_WLAN_%s_RTS_Threshold` | `rts` |
| `ARC_WLAN_%s_RadioMode` | `gmode` / `nmode` / `vhtmode` / `nac` |

### 2.3 回传 / 前传

| ARC 键 | nvram 键 |
|---|---|
| `ARC_WLAN_24G_SSID_0_ESSID`（FH） | `fh_ssid` |
| `ARC_WLAN_24G_SSID_0_WPA_Passphrase`（FH） | `fh_wpa_psk` |
| `ARC_WLAN_24G_SSID_0_WPA_Cipher`（FH） | `fh_crypto` |
| `ARC_WLAN_24G_STA_SSID_0_ESSID`（BH） | `bh_ssid` |
| `ARC_WLAN_24G_STA_SSID_0_WPA_Passphrase`（BH） | `bh_wpa_psk` |
| `ARC_WLAN_24G_STA_SSID_0_WPA_Cipher`（BH） | `bh_crypto` |
| `ARC_WBD_Mode` | `wbd_mode` / `multiap_mode` |
| — | `map_bss_names` / `fh_map` / `bh_map` / `fh_band_flag` / `bh_band_flag` |
| — | `multiap_registrar` / `wbd_bh_opt` / `wbd_bounce_detect` / `wbd_remove_client` / `wbd_tbss_algo` |

### 2.4 LAN / 系统

| ARC 键 | nvram 键 |
|---|---|
| `ARC_LAN_0_Ifname` | `lan_ifname` |
| `ARC_LAN_0_BridgedIfname` | `lan_ifnames` |
| `ARC_LAN_0_MACaddr` | `lan_hwaddr` |
| `ARC_SYS_InternetConn` | `ETH`（InternetConn 相关） |
| `ARC_WLAN_%s_Interface` | `<prefix>_vifs` |

---

## 3. 同步函数

`do_sync(cmd, ...)` 是一个 switch：

| cmd | 动作 |
|---:|---|
| 0 / 1 | `set_prefix`（24G / 5G） |
| 2 / 3 | 前缀 + `get_wbd_mode` / `get_backhaul_band` |
| 4..8 | 调各 `sh_wl_*`（channel / mode / mrate / txbf / vht / ampdu_rts / power / secmode / vifs） |
| 9 | `defaults_nvram` |
| 10 | `merge_new_glbcfg` |
| 11 / 12 | 其他（defaults / 清理） |

底层：

```
nvram_set_brcm / nvram_get_brcm / nvram_unset_brcm
nvram_commit_brcm
wl -i <if> <cmd> <value>
mapi_ccfg_get_str(handle, "ARC_WLAN_...", buf, len)
```

即：**读 glbcfg → 拼 nvram 键 → `nvram_set_brcm` → `nvram_commit_brcm`**。

---

## 4. 例子

```sh
# 改 2.4G 第一个 VAP 的 SSID
mng_cli set ARC_WLAN_24G_SSID_1_ESSID="Guest"
mng_cli commit
# 同步到驱动
arc_nvram_sync   # 或由 wlan agent 触发
```

等价于：

```
nvram set wl1.1_ssid=Guest
nvram set wl1.1_closed=0
nvram set wl1.1_bss_enabled=1
nvram commit
wl -i wl1.1 ssid Guest
```

---

## 5. 观察

1. **nvram 里是明文**：`wl1_wpa_psk`、`bh_wpa_psk`、`fh_wpa_psk` 都是明文口令。
2. **`closed` 控制隐藏 SSID**：`ARC_WLAN_*_Hide=1` → `closed=1`。
3. **`macmode` 既是 allow/deny 又是启用开关**，脚本里要小心。
4. **回传用独立的前缀**（`bh_` / `fh_`），不是普通的 `wl*_`。
5. **`do_sync` 的 cmd 编号**是内部 ABI，改固件时不能乱动。

---

## 6. 证据索引

| 内容 | 位置 |
|---|---|
| 映射库 | `/usr/lib/libarc-nvramsync.so.0.1` |
| 同步工具 | `/usr/sbin/arc_nvram_sync` |
| 前缀/键名 | `.rodata` 里的 `wl0_`/`wl1_`/`fh_`/`bh_`/`ARC_WLAN_*` |
| 函数 | `do_sync` @ `0x5D98`、`set_prefix` @ `0x5B40`、`sh_wl_vifs` @ `0x30A0` |
