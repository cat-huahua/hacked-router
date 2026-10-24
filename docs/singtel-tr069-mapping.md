# TR-069 参数 → `ARC_*` 配置键的映射

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/sbin/tr69`（`arc_cfg_*` 调用 + `ARC_*` 键字符串）
> 结论：**TR-069 客户端直接调用 `arc_cfg_get/set` 操作 `.glbcfg`，
> 不经过 CMS（`libcms_*`）。**

---

## 1. 架构

```
ACS
 ↓ CWMP/SOAP
/usr/sbin/tr69
 ↓ arc_cfg_get / arc_cfg_set / arc_cfg_get_idx1 / set_idx1 …
.mglbcfg（通过 mng/midcore）
```

`tr69` 导入的符号：

```
arc_cfg_get / arc_cfg_set
arc_cfg_get_idx1 / set_idx1 / unset_idx1
arc_cfg_get_idx2 / set_idx2
arc_cfg_get_long / set_long
arc_cfg_cache_get*
arc_cfg_cmp_idx1
arc_cfg_get_idx1_limit / idx2_limit
arc_cfg_get_long_vDft_auto
```

也就是说：TR-069 的 Get/SetParameterValues 最终落到 **`mng_cli` 同一套配置引擎**，
而不是 `libcms_core`。

---

## 2. 能通过 TR-069 改的键（从字符串提取）

### 2.1 系统 / 远程管理

```
ARC_SYS_Password                 ← 管理密码
ARC_SYS_HTTP_Enable / HTTPS_Enable
ARC_SYS_LoginEnable
ARC_SYS_InternetConn
ARC_SYS_ProductClass
ARC_ROOT_Passwd                  ← root/SSH 口令
ARC_SSHD_Enabled / Iface / Port
ARC_TELNETD_ENABLE
ARC_HTTPD_JSONAPI_Enable         ← ★ 隐藏 JSON API
ARC_UI_WEB_REMOTEMN_Enable / Https / Port / Password
ARC_UI_WEB_REMOTEMN_ExposeToAny
ARC_UI_WEB_REMOTEMN_ExposeToIP_%d_Start / End
ARC_UI_WEB_REMOTEMN_Bridge_Enable
ARC_NOT_OOB
```

### 2.2 自动升级

```
ARC_SYS_AUTOFW_Enable / Url
ARC_SYS_AUTOFW_BootUpCheckStartTime / EndTime
ARC_SYS_AUTOFW_PeriodCheckTime
ARC_SYS_AUTOFW_FailRetryInterval
ARC_SYS_AUTOFW_MaximumCheckTimes
ARC_SYS_AUTOFW_RebootDayOfWeek / RebootStartTime / RebootEndTime
```

### 2.3 防火墙 / DPI / ALG

```
ARC_FIREWALL_IDS_AntiDOS / BlockNetbios / BlockWANPing
ARC_DPI_Enable / PacketsCount
ARC_ALG_FTP_Enable / TFTP_Enable / RTSP_Enable / SIP_Enable / H323_Enable
```

### 2.4 WAN / LAN / IPv6

```
ARC_WAN_%d_IP4_Addr / DNS / Proto / Uptime
ARC_WAN_%s_IP4_Proto
ARC_WAN_DefaultRouteIdx
ARC_WAN_EnableInternet
ARC_LAN_0_IP4_BridgeAddr / BridgeDHCPAddr / BridgeDHCPDNS /
              BridgeDHCPGateway / BridgeDHCPNetmask / BridgeProto
ARC_LAN_0_DHCP4S / DHCP4S_DNS_Mode
ARC_LAN_0_MACaddr / Ifname / IP6_DNS_Mode
ARC_IP6_TunnelType / 6RD / DSLITE / MAPT
```

### 2.5 WLAN / WPS

```
ARC_WLAN_24G_SSID_0_Enable / ESSID
ARC_WLAN_24G_SSID_0_WPA_Passphrase
ARC_WLAN_24G_SSID_0_WEP_Key_0
ARC_WLAN_24G_SSID_0_WPS_Enable
ARC_WLAN_24G_SSID_1_WPS_Enable
ARC_WLAN_24G_STA_SSID_0_Enable / Mode
ARC_WLAN_24G_BandSteering
ARC_WLAN_24G_ARC_Channel
ARC_WLAN_24G_ChipID
ARC_WLAN_24G_TxBFEnable
ARC_WLAN_5G_...（同上）
ARC_WBD_Mode
ARC_LAN_0|ARC_WLAN_24G_SSID_0_MACFILTER
```

### 2.6 NAT / 测速 / 其它

```
ARC_NAT_PORTMAP / ARC_NAT_PORTMAP_%d
ARC_SPDSVC_*（Mode/Direction/ServerIpAddr/TcpPort/StepDuration/
              PacketLength/StartingBwKbps/Algorithm/MaxSteps/
              AcceptablePercentageLoss/SpdsvcState/TestedTimes）
ARC_UPNP_Enable
```

---

## 3. 能力边界

- **能读/写**：上面列出的键（由 `arc_cfg_*` 支持）；
- **不能直接**：CMS 数据模型里的 TR-098 参数（那是 `libcms_*` 的路径）；
- **特殊动作**：`SetParameterValues` 后可能触发 `tr69_*` 动作链
  （见 [singtel-tr069.md](singtel-tr069.md)）。

---

## 4. 安全观察

1. **ACS 可以直接打开 telnet/SSH/JSON API**：
   `ARC_TELNETD_ENABLE`、`ARC_SSHD_Enabled`、`ARC_HTTPD_JSONAPI_Enable`
   都在可写键里 —— 如果 ACS 被攻陷，等于拿到设备管理面。
2. **ACS 可以改管理密码/root 口令**：
   `ARC_SYS_Password`、`ARC_ROOT_Passwd`。
3. **ACS 可以改自动升级 URL/时间窗**：`ARC_SYS_AUTOFW_Url` 等。
4. **默认 ACS 凭据是 `singtel/singtel`**（见 tr069 文档），
   且 45 秒一次 Inform —— 攻击面持续在线。
5. **TR-069 走 `.glbcfg` 而不是 CMS**：两套配置系统可能不同步，
   ACS 改的值可能被 CMS/本地覆盖。

---

## 5. 证据索引

| 内容 | 位置 |
|---|---|
| TR-069 客户端 | `/usr/sbin/tr69` |
| 配置 API | `arc_cfg_get/set` / `arc_cfg_*_idx*` / `arc_cfg_cache_*` |
| 可写键 | `tr69` 内的 `ARC_*` 字符串（上面分类） |
| 动作 | `/usr/share/msg/tr69_*`（10 个） |
| 默认 ACS | `.glbcfg` 的 `ARC_TR69_*` |
