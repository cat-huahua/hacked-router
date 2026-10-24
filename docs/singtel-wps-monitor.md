# `wps_monitor`：Broadcom WPS 状态机与 PIN 锁定

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/bin/wps_monitor`（175 KB，Broadcom WSC）
> 一句话：**完整 WPS（EAPOL M1–M8 + UPnP WFAWLANConfig + 1905），
> 自带 `wps_aplockdown` 防 PIN 爆破机制。**

---

## 1. 三条入口

`wps_monitor` 同时支持：

| 入口 | 证据 |
|---|---|
| **EAPOL/WSC** | `wps_eapol_parse_msg` / `wps_eapol_send_data`、`WFA-SimpleConfig-Enrollee-1-0` |
| **UPnP WFAWLANConfig** | `urn:schemas-wifialliance-org:service:WFAWLANConfig:1`、`/control?WFAWLANConfig`、`/event?WFAWLANConfig` |
| **IEEE1905** | `1905_com_socket`、`wps_osl_1905_send_response`、`M2 message confirue to 1905` |

也就是说：手机 App、WPS 按钮、mesh 回传可以分别通过 UPnP / EAPOL / 1905 触发 WPS。

---

## 2. nvram 键

`wps_monitor` 读写这些 Broadcom nvram 键：

```
wps_mode                 wps_action
wps_config_command       wps_config_method
wps_method               wps_device_pin
wps_device_name          wps_mfstring / wps_modelname / wps_modelnum
wps_pairing_auth         wps_delay_deauth_ms
wps_custom_ifnames       wps_pbc_apsta
wps_pbc_ap_index         wps_pbc_ap_ifname
wps_akm / wps_crypto / wps_psk / wps_ssid
wps_enr_ssid / wps_enr_bssid / wps_enr_wsec / wps_enr_scan
wps_sta_pin              wps_stareg_ap_pin
wps_autho_sta_mac        wps_sta_mac
wps_uuid                 wps_random_ssid_prefix
ess%d_wps_oob            lan_wps_oob
```

状态/结果：

```
wps_proc_status          wps_scstate
wps_pinfail              wps_pinfail_mac / wps_pinfail_name / wps_pinfail_state
wps_aplockdown           wps_aplockdown_forceon / wps_aplockdown_disable
wps_lock_start_cnt       wps_lock_forever_cnt
```

---

## 3. WPS 状态机

从 `arc_wps_led.sh` 的注释可以读出 `WPS_SCSTATE`：

```
WPS_INIT, WPS_ASSOCIATED, WPS_OK, WPS_MSG_ERR, WPS_TIMEOUT,
WPS_SENDM2, WPS_SENDM7, WPS_MSGDONE, WPS_PBCOVERLAP,
WPS_FIND_PBC_AP, WPS_ASSOCIATING, WPS_FIND_SEL_AP
```

`wps_proc_status`（Broadcom）在 `arc_wps_led.sh` 里这样用：

| 值 | 含义 | LED |
|---:|---|---|
| 0 | idle | 保持 |
| 1/5/6/7/9/10/11 | 进行中 | 慢闪 |
| 2 | 成功 | mesh 常亮 |
| 3/4 | 超时/错误 | 快闪 |
| 8 | PBC overlap | 快闪 |

EAPOL 消息序列（`strings` 里可见）：

```
M1 M2 M2D M3 M4 M5 M7 M8 NACK DONE UNKNOWN
```

即标准 WSC Registrar/Enrollee 流程。

---

## 4. ★ PIN 爆破防护（`wps_aplockdown`）

`wps_monitor` 里有：

```
wps_pinfail=%d
wps_aplockdown=%d
wps_lock_start_cnt
wps_lock_forever_cnt
/tmp/wps_pin_failed_cnt
brcm_get_lock / brcm_release_lock
```

逻辑（从键名和赋值顺序推断）：

1. 每次 PIN 失败：`wps_pinfail++`，并记录失败的 STA MAC；
2. 达到 `wps_lock_start_cnt`：进入 **`wps_aplockdown=1`**（临时锁定）；
3. 持续失败到 `wps_lock_forever_cnt`：**永久锁定**（`wps_aplockdown_forceon`）；
4. 锁定期间拒绝新的 PIN 尝试；
5. `wps_aplockdown_disable` 可以关闭锁定（调试/工厂用）。

> 这是比很多“裸 WPS”路由器更好的设计：**PIN 爆破会被 AP 锁定**。
> 但 `/tmp/wps_pin_failed_cnt` 在 tmpfs，重启会清零。

---

## 5. 文件与进程

```
/bin/wps_monitor              主程序
/sbin/arc_wps_monitor         启动/停止
/sbin/arc_wps_led.sh          状态轮询 + LED
/usr/share/msg/WPS_STATUS     WPS 状态动作
/usr/share/msg/WPS_CANCEL     WPS 取消动作
/tmp/wps_monitor.pid
/tmp/wps_pin_failed_cnt
```

启动（`arc_wps_monitor`）：

```sh
ps | grep wps_monitor ... || /bin/wps_monitor &
```

停止：`killall -9 wps_monitor`。

---

## 6. 与 `.glbcfg` 的关系

`.glbcfg` 里没有 `wps_aplockdown`，但有：

```
ARC_WLAN_24G_WPS_Enable=1
ARC_WLAN_24G_WPS_PINEnable=0
ARC_WLAN_*_SSID_*_WPS_Enable
ARC_WLAN_*_SSID_*_WPS_ExRegistrarPIN=12345670
```

`arc_wlan` 的 `wps_pbc` / `wps_sta_pin` 会调用：

```sh
hostapd_cli -i wlan0 wps_pbc
hostapd_cli -i wlan0 wps_pin any <pin> 120
```

即 **WPS 实际由 hostapd + wps_monitor 共同完成**。

---

## 7. 安全观察

1. **有 PIN 锁定**：`wps_aplockdown` / `wps_lock_*_cnt` 能挡住大部分在线爆破。
2. **但回传 WPS 默认开、PIN 默认 12345670**（见
   [singtel-wps-and-mesh-pairing.md](singtel-wps-and-mesh-pairing.md)）——
   如果板级 `wps-pin` 没覆盖，默认 PIN 仍然是可预测的。
3. **`wps_aplockdown_disable`** 如果被设为 1，锁定就失效（工厂/调试残留风险）。
4. **`/tmp/wps_pin_failed_cnt` 重启清零** —— 重启可以重置失败计数。
5. **UPnP WFAWLANConfig** 是一个额外的 WPS 入口，很多路由器默认关 UPnP；
   这台默认 `ARC_UPNP_Enable=1`，值得注意。

---

## 8. 证据索引

| 内容 | 位置 |
|---|---|
| WPS 主程序 | `/bin/wps_monitor` |
| 状态机函数 | `reg_proto_process_m1..m8`、`wps_eapol_parse_msg` |
| UPnP | `WFAWLANConfig1`、`/control?WFAWLANConfig` |
| 1905 | `1905_com_socket`、`wps_osl_1905_send_response` |
| 锁定 | `wps_aplockdown`、`wps_lock_start_cnt`、`wps_lock_forever_cnt`、`/tmp/wps_pin_failed_cnt` |
| 状态码 | `arc_wps_led.sh` 的 `WPS_SCSTATE` 注释 |
