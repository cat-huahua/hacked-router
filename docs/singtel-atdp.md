# Singtel 的 ATDP：1905.1 上的 Arcadyan 私有传输

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`libArcShareATDP.so`、`/lib/modules/4.1.38/extra/drv_atdp.ko`
> 一句话：**OWL 的 1905 管理帧由内核模块 `drv_atdp.ko` 通过
> `/dev/ATDP_CDRV` 收发的 VendorSpecific TLV 承载。**

---

## 1. 组件

| 组件 | 作用 |
|---|---|
| `drv_atdp.ko` | 内核模块：1905.1 CMDU 解析、VendorSpecific TLV 打包/解包 |
| `/dev/ATDP_CDRV` | 字符设备，用户态通过 ioctl 收发 |
| `libArcShareATDP.so` | 用户态库：设备 ID/MAC、拓扑、链路检测、上行状态 |
| `libArcOWLcore.so` | 上层 OWL/steering |

ioctl 示例（字符串）：

```
PATDP_ARC_LINUX_IOCTL_TX_OWL_MGMT_FRAME_CMD
%s[%d]: ... return -1
```

---

## 2. 1905 CMDU 与 TLV

内核模块里的类型名：

```
AlMacAddressType_TLV          AL MAC 地址
ARC_vSpf_31_TLV               厂商自定义 TLV 31
ARC_vSpf_35_TLV               厂商自定义 TLV 35
ARC_vSpf_FUTURE_EXTENSION_01_TLV
arc_tlvType / arc_tlvLength
arc_pack_VendorSpecific_TLV_tx
arc_decode_VendorSpecific_TLV_tx
```

错误：

```
ERROR: p1905_1_rcv: unknown control packets, cmdu_hdr->messageType = 0x%04x
```

即：它按 1905.1 的 CMDU 头（messageType）分派，未知类型直接报错。

---

## 3. 控制命令

```
_ARC_ATDP_CTRL_MGMT_CMD_LOOSE_UPLINK    上行丢失
_ARC_ATDP_CTRL_MGMT_CMD_TPLG_CHNAGE     拓扑变化
_ARC_ATDP_CTRL_MGMT_TOTAL_CMDS
```

## 4. 速率测试（ATDP 内置）

```
ARC_ATDP_SPEED_TEST_LOOPBACK_MODE
ARC_ATDP_SPEED_TEST_OBTAIN_THROUGHPUT_MODE
ARC_ATDP_SPEED_TEST_RELAY_MODE
ARC_ATDP_SPEED_TEST_RESET_MODE
ARC_ATDP_SPEED_TEST_RX_MODE
ARC_ATDP_SPEED_TEST_TX_MODE
```

即：ATDP 层可以直接做 loopback/relay/tx/rx 吞吐测试，
用于 mesh 回传链路质量评估。

---

## 5. 上行与回传跟踪

```
ARC_ATDP_IF_UPLINK_STATE_S / _T
atdp_backhaul_tracking_entry
ATDP_BRI_KD
libArcATDP_Update_Uplink_Port_State
libArcATDP_Send_Link_Detection_Packet
libArcATDP_obtain_group_count_by_group_ssid
libArcATDP_Setup_New_Grouping_ID
libArcATDP_obtain_compare_with_uptime_and_mac
```

接口枚举（调试输出）：

```
Ethernet Port 1/2 (%u): IF MAC: ...
WiFi 2.4 G Client (%u): IF MAC: ...
WiFi 5 G High Band Client (%u): IF MAC: ...
WiFi 5 G Low Band Client (%u): IF MAC: ...
```

## 6. 用户态 API（`libArcShareATDP.so`）

```
libArc1905_ObtainDeviceId / ReleaseDeviceId
libArc1905_obtain_device_MAC
libArc1905_obtain_basic_device_info
libArc1905_obtain_driver_ready_state
libArc1905_obtain_IPV4_station_list
libArc1905_obtain_owl_tplg_map / reset_tplg_map
libArc1905_deceide_home_network_master_device
libArc1905_monitor_tplg_change_notification
libArc1905_device_role_change_notification
libArc1905_internet_admin_change_notification
libArc1905_root_ap_profile_change_notification
libArc1905_send_arp_to_server
libArc1905_send_dhcpc_discover_to_server
libArc1905_send_dhcpServer_found_notification
libArc1905_send_speed_test
libArc1905_send_wifi_restart_notification
libArc1905_send_uplink_wifi_path_factor_change_notification
libArc1905_trigger_shutdown_AP_event
libArc1905_link_metrx_dump
libArc1905_tx_atdp_ctrl_mgmt_frame / tx_owl_mgmt_frame
libArc1905_rx_owl_mgmt_frame
```

---

## 7. 内核 ↔ 用户态消息队列类型

`drv_atdp.ko` 的 `_P19051_ARC_LINUX_MSG_QUE_FMT_TYPE`（DWARF 枚举）：

| 值 | 名字 |
|---:|---|
| 0 | `P19051_QUE_RCV_LLDP` |
| 1 | `P19051_QUE_RCV_1905_1_FRAME` |
| 2 | `P19051_QUE_RCV_IF_UP` |
| 3 | `P19051_QUE_RCV_IF_DOWN` |
| 4 | `P19051_QUE_RCV_STA_IN` |
| 5 | `P19051_QUE_RCV_STA_OUT` |
| 6 | `P19051_QUE_SEND_VENDOR_PKT_OUT` |
| 7 | `P19051_QUE_RCV_DB_SYNC` |
| 8 | `P19051_QUE_SEND_LNK_METRIC_QUERY` |
| 9 | `P19051_QUE_SEND_TPLG_DISC_AND_LLDP` |
| 10 | `P19051_QUE_LNK_METRIC_QUERY_TIMEOUT` |
| 11 | `P19051_QUE_TPLG_QUERY_TIMEOUT` |
| 12 | `P19051_QUE_TPLG_DUMP` |
| 13 | `P19051_QUE_SHUTDOWN_DEVICE` |
| 14 | `P19051_QUE_PENDING_DEVICE` |
| 15 | `P19051_QUE_RESUME_DEVICE` |
| 16 | `P19051_QUE_SEND_TEST_DHCPC_DISCOVER` |
| 17 | `P19051_QUE_SEND_TEST_ARP` |
| 18 | `P19051_QUE_RESET_WHOLE_TOPOLOGY_MAP` |
| 19 | `P19051_QUE_RENEW_INTERFACE_DEVICE_POINTER` |
| 20 | `ATDP_QUE_DMR_MSG_COLLISION` |
| 21 | `ATDP_QUE_DMR_MSG_COLLISION_TRIGER` |
| 22 | `ATDP_QUE_DMR_MSG_OVER_CAC_TIME` |
| 23 | `ATDP_QUE_TPLG_CHANGE_OLD_DEVICE_LEAVE` |
| 24 | `ATDP_QUE_TPLG_CHANGE_NEW_DEVICE_TPLG_QUERY_DONE` |
| 25 | `ATDP_QUE_TPLG_CHANGE_NEW_NEIGHBOR_ENTRY_FOUND` |
| 26 | `ATDP_QUE_TPLG_CHANGE_DEL_OLD_NEIGHBOR_ENTRY_FOUND` |
| 27 | `ATDP_QUE_TPLG_CHANGE_BACKHAUL_CHANGE_PROPERTY_VALUE` |
| 28 | `ATDP_QUE_TPLG_CHANGE_BACKHAUL_CHANGE_UPLINK_INTERFACE` |
| 29 | `ATDP_QUE_TPLG_CHANGE_MASTER_UPDATE` |
| 30 | `P19051_QUE_NO_OF_RCV_MSG` |

这张表就是内核模块和用户态 `libArcShareATDP.so` 之间的消息类型字典。

---

## 8. 安全观察

1. **ATDP 是二层明文**：VendorSpecific TLV 没有加密/签名；
   同一 L2 域的相邻设备可以注入/伪造 CMDU。
2. **控制命令可影响拓扑**：`LOOSE_UPLINK`、`TPLG_CHNAGE` 如果被伪造，
   可能触发主节点重新选举/回传切换。
3. **内置测速**：攻击者可以触发 loopback/relay 测速，消耗带宽。
4. **`/dev/ATDP_CDRV` 权限**：用户态可打开它发帧，
   权限取决于设备节点权限（通常 root）。
5. **调试计数器**（Discover/Data Query/Data Response）会暴露拓扑活动。

---

## 9. 证据索引

| 内容 | 位置 |
|---|---|
| 内核模块 | `/lib/modules/4.1.38/extra/drv_atdp.ko` |
| 字符设备 | `/dev/ATDP_CDRV` |
| TLV | `ARC_vSpf_31_TLV` / `_35_TLV` / `FUTURE_EXTENSION_01` |
| 控制命令 | `_ARC_ATDP_CTRL_MGMT_CMD_*` |
| 测速模式 | `ARC_ATDP_SPEED_TEST_*` |
| 用户态库 | `libArcShareATDP.so`（`libArc1905_*`） |
