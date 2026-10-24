# OWL 的 IEEE1905 传输与 steering 函数地图

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`libArcOWLcore.so`、`libArcOWLapi.so`、`libArcShareATDP.so`
> 作用：OWL（SON）跑在 **IEEE1905.1** 上，负责拓扑、客户端上报和 band steering。

---

## 1. 1905 传输层

```
libArc1905_ObtainDeviceId        取 1905 Device ID
libArc1905_obtain_device_MAC     取 AL MAC
libArc1905_tx_owl_mgmt_frame     发 OWL 管理帧
libArc1905_rx_owl_mgmt_frame     收 OWL 管理帧
libArc1905_monitor_tplg_change_notification   拓扑变化通知
libArc1905_flush_rx_queue
g_new_arc_1905_fd                1905 socket fd
```

拓扑标识：

```
master_ieee1905_id: %02X:%02X:%02X:%02X:%02X:%02X
OWL-%s(%s) join topology
OWL-%s(%s) leave topology
Ieee1905NeighborNumberOfEntries=%d
Neighbor[%d]
Neighbor: %s
```

即：每个 OWL 节点用 1905 Device ID / AL MAC 标识，
通过 join/leave 消息维护拓扑，邻居表存在 `Ieee1905Neighbor*`。

---

## 2. 客户端信息（assoc / unassoc）

```
bcm_wifi_get_assoc_list
owl_wifi_get_assoc_list
owl_wifi_get_associated
owl_wifi_get_neighbor_sta
assoc_num=%d, unassoc_num=%d
```

编码/解码（跨进程/跨节点传输）：

```
owl_txrx_data_encode_unassoc_sta_info_to_buffer
owl_txrx_data_encode_unassoc_sta_list_to_buffer
owl_txrx_data_decode_unassoc_sta_info_from_json
owl_txrx_data_decode_unassoc_sta_list_from_json
owl_wifi_assoc_sta_data_htonX / ntohX
owl_wifi_assoc_sta_list_htonX / ntohX
owl_wifi_unassoc_sta_data_htonX
```

即：关联/未关联客户端列表会被序列化成 buffer 或 JSON，
再做 hton/ntoh 后通过 1905 发给主节点。

字段（从日志）：

```
MAC address   ASSOC_TIME RSSI RSSI_MAX RSSI_MIN BandId
```

---

## 3. Steering（band steering）

### 触发条件

```
RSSI High  2G→5G
RSSI Low   5G→2G
RSSI LOW in 2G / 5G（AP roaming）
2G Channel OverLoad（2G→5G）
5G Channel OverLoad（5G→2G）
Unknown
```

### 两种模式

```
Mode = BTM      （802.11v BSS Transition Management）
Mode = Legacy   （deauth/黑名单）
```

### 关键函数

```
owl_wifi_BTM_steer
owl_wifi_do_BTM_steer
owl_wifi_config_steering
owl_wifi_enable_steering
owl_wifi_check_steer_prohibit_time
owl_wifi_do_legacy_steer
owl_func_trigger_wifi_legacy_steer
owl_rx_func_trigger_wifi_steering
owl_rx_func_trigger_wifi_legacy_steer
owl_wifi_process_beacon_measurement
owl_wifi_process_neighbor_report
owl_wifi_rrm_send_beacon_request
```

### 状态/记录

```
/data/SteeringEvent_All
./tmp/steering_record（运行时）
OWL-%s:STA(%s) Leagacy Steering Black List Added
Current= %d Last_steer=%d [%d] Prohibit_time=%d
CNT=%d Assoc=%d Prohibit=%d
```

配置键：

```
ARC_OWL_steer_capability / ARC_OWL_Steer_prohibit
ARC_OWL_WIFI_CONFIG_STEER_CAPABILITY / STEER_PROHIBIT
ARC_OWL_WIFI_CONFIG_CHANLOAD_REPORT
```

---

## 4. 事件处理

收到的 1905 消息分派到：

```
owl_rx_func_add_wifi_sta_steer_info
owl_rx_func_assoc_station_join
owl_rx_func_assoc_station_leave
owl_rx_func_report_assoc_station_info
owl_rx_func_report_unassoc_station_info
owl_rx_func_update_assoc_station_info
owl_rx_func_update_unassoc_station_info
owl_rx_func_trigger_wifi_steering
owl_rx_func_trigger_wifi_legacy_steer
```

发送/记录：

```
owl_func_add_wifi_sta_steer_info
owl_func_apply_assoc_station_info
owl_func_apply_assoc_station_list
owl_func_get_assoc_stations_list
owl_func_record_steering_result
owl_func_record_steering_result_all
owl_sys_save_wifi_steer_station_info
owl_sys_record_steering_result
```

---

## 5. 与 HTTP / dbus 的关系

| 面 | 入口 |
|---|---|
| 本地 HTTP | `/status/tplg`、`/status/stainfo`、`/status/Wificonfig`（见 owl-api 文档） |
| dbus | `arca.dbus.owl`（`CMD_BOOT/START/STOP/RESTART`） |
| 1905 | `libArc1905_tx/rx_owl_mgmt_frame` |
| 云端 | `devices/<id>/{adornment,desired_state,direct}` |

同一份拓扑/steering 状态会被这三条路径读取或驱动。

---

## 6. 安全观察

1. **1905 是二层协议**：能发 1905 帧的相邻设备可以伪造 join/leave、
   上报假的 assoc/unassoc 列表或触发 steering。
2. **没有看到 1905 层的加密/签名**（OWL 依赖 L2 隔离）。
3. **Steering 可以被伪造触发**：如果攻击者在同一 L2 域，可能把客户端
   踢到指定频段/AP（拒绝服务或降级攻击）。
4. **`/data/SteeringEvent_All` 记录历史**：可用来审计谁被踢过。
5. **`ARC_OWL_Steer_prohibit`** 可以禁止 steering；关掉可降低被伪造触发的风险。

---

## 7. 证据索引

| 内容 | 位置 |
|---|---|
| 1905 传输 | `libArcOWLcore.so`：`libArc1905_*` |
| 拓扑 | `OWL-%s(%s) join/leave topology`、`Ieee1905Neighbor*` |
| Steering | `owl_wifi_BTM_steer`、`owl_wifi_do_legacy_steer`、`owl_func_*` |
| 客户端列表 | `owl_txrx_data_*_unassoc_sta_*`、`bcm_wifi_get_assoc_list` |
| 记录 | `/data/SteeringEvent_All` |
| 配置 | `ARC_OWL_*` |
