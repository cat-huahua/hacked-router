# ATDP 的 1905 TLV 精确结构（来自 `drv_atdp.ko` 的 DWARF）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/lib/modules/4.1.38/extra/drv_atdp.ko`（**带 debug_info，未 strip**）
> 方法：`readelf --debug-dump=info` 直接读出结构体定义，不靠猜。

---

## 0. 关键修正

`tlvLength` 是 **u16（2 字节）**，不是 1 字节。
（用结构体 byte_size 反推：`AlMacAddressType_TLV` = 1+2+6 = 9。）

`tlvType` 是 u8。

---

## 1. `Cmdu_Header`（8 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | `messageVersion` |
| 1 | u8 | `reservedField` |
| 2 | u16 | `messageType` |
| 4 | u16 | `messageId` |
| 6 | u8 | `fragmentId` |
| 7 | u8 | `lastFragment_Relay_Indicator` |

---

## 2. `AlMacAddressType_TLV_t`（9 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | `tlvType` |
| 1 | u16 | `tlvLength` |
| 3 | u8[6] | `AL_mac` |

## 3. `MacAddressType_TLV_t`（9 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | `tlvType` |
| 1 | u16 | `tlvLength` |
| 3 | u8[6] | `intf_mac` |

---

## 4. `ARC_vSpf_31_TLV_t`（10 字节）

厂商自定义 TLV 31：

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | `tlvType` |
| 1 | u16 | `tlvLength` |
| 3 | u8[3] | `vendorSpecific_OUI` |
| 6 | u8 | `arc_tlvType` |
| 7 | u16 | `arc_tlvLength` |
| 9 | u8[1] | `payload_data`（变长） |

---

## 5. `ARC_vSpf_35_TLV_t`（44 字节）

厂商自定义 TLV 35（节点信息/上行）：

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | `tlvType` |
| 1 | u16 | `tlvLength` |
| 3 | u8 | `RouterFlag` |
| 4 | u32 | `Jiffies` |
| 8 | u32 | `UplinkPath` |
| 12 | char[32] | `friendlyName` |

---

## 6. `ARC_vSpf_FUTURE_EXTENSION_01_TLV_t`（131 字节）

链路状态/速率/RSSI 的完整快照：

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | `tlvType` |
| 1 | u16 | `tlvLength` |
| 3 | u8 | `WiFi_Band_Uplink_Type` |
| 4 | u8 | `Ether1_Link_Result` |
| 5 | u8[6] | `Ether1_IF_MAC` |
| 11 | u8 | `Ether2_Link_Result` |
| 12 | u8[6] | `Ether2_IF_MAC` |
| 18 | u8 | `WiFi2_4G_Link_Result` |
| 19 | u8[6] | `WiFi_2_4G_MAC` |
| 25 | u8 | `WiFi5G_Low_Band_Link_Result` |
| 26 | u8[6] | `WiFi5G_Low_Band_IF_MAC` |
| 32 | u8 | `WiFi5G_High_Band_Link_Result` |
| 33 | u8[6] | `WiFi5G_High_Band_IF_MAC` |
| 39 | u32 | `Ether1_DataRate` |
| 43 | u32 | `Ether2_DataRate` |
| 47 | u32 | `WiFi_2_4G_DataRate` |
| 51 | u32 | `WiFi5G_Low_Band_DataRate` |
| 55 | u32 | `WiFi5G_High_Band_DataRate` |
| 59 | u8 | `Ether1_full_duplex` |
| 60 | u32 | `Ether1_link_speed` |
| 64 | u8 | `Ether2_full_duplex` |
| 65 | u32 | `Ether2_link_speed` |
| 69 | s32 | `WiFi_2_4G_rssi` |
| 73 | u32 | `WiFi_2_4G_link_rate` |
| 77 | s32 | `WiFi5G_Low_Band_rssi` |
| 81 | u32 | `WiFi5G_Low_Band_link_rate` |
| 85 | s32 | `WiFi5G_High_Band_rssi` |
| 89 | u32 | `WiFi5G_High_Band_link_rate` |
| 93 | u8[38] | `futureReserved` |

> 这就是 ATDP 用来上报“每条链路是否通、速率多少、RSSI 多少”的结构。

---

## 7. 链路度量（1905 Link Metric）

### `RxIntfPair_t`（12 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8[6] | `intf_mac` |
| 6 | u8[6] | `nbr_Intf_mac` |

### `RxLinkMetric_TLV_t`（159 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | `tlvType` |
| 1 | u16 | `tlvLength` |
| 3 | u8[6] | `Al_mac` |
| 9 | u8[6] | `nbr_AL_mac` |
| 15 | `RxIntfPair_t[12]` | `rxIntfPair`（144 字节） |

### `LinkMetric_TLV_t`（318 字节）

```
+0    tx : RxLinkMetric_TLV_t (159)
+159  rx : RxLinkMetric_TLV_t (159)
```

---

## 8. 其它结构

### `WiFiSpecificInfo_t`（10 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8[6] | `BSSID` |
| 6 | u8 | `role` |
| 7 | u8 | `apChBand` |
| 8 | u8 | `apChCentFrqIdx1` |
| 9 | u8 | `apChCentFrqIdx2` |

### `InfoLocalIntf`（19 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8[6] | `intf_mac` |
| 6 | u8 | `mediaType` |
| 7 | u8 | `len_MediaSpecificInfo` |
| 8 | 变长 | `mediaSpecificInfo` |

---

## 9. DMR 消息（Data Measurement Request）

### `atdp_dmr_packet_t`（9 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | `op` |
| 1 | u16 | `length` |
| 3 | u8 | `current_use` |
| 4 | u32 | `channel` |
| 8 | u8 | `BW` |

### `DMR_NOP_Timeout_T`（16 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u32 | `hit_channel` |
| 4 | u32 | `channel` |
| 8 | u8 | `BW` |
| 12 | u32 | `time_down_ctr` |

### `DMR_ARC_TPLG_CHANGE_INFO_T`（12 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u32 | `change_reason` |
| 4 | u8[6] | `tplg_change_device_mac` |

### `DMR_Message_T`（20 字节）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u32 | `message_type` |
| 4 | union(16) | `union_data` |

`union_data` 的成员：

```
mgmt_cmd
dmr_monitored_pkts   (atdp_dmr_packet_t)
d_Channel
nop_Channel          (DMR_NOP_Timeout_T)
tplg_notification    (DMR_ARC_TPLG_CHANGE_INFO_T)
```

> DMR 是 ATDP 的“测量/控制”消息通道：信道测量、NOP 超时、
> 拓扑变化通知都从这里走。

---

## 10. 枚举值（同样来自 DWARF）

### `_ARC_ATDP_CTRL_MGMT_CMD_ENUM`

| 值 | 名字 |
|---:|---|
| 0 | `_ARC_ATDP_CTRL_MGMT_CMD_TPLG_CHNAGE` |
| 1 | `_ARC_ATDP_CTRL_MGMT_CMD_LOOSE_UPLINK` |
| 2 | `_ARC_ATDP_CTRL_MGMT_TOTAL_CMDS` |

### `_P19051_ARC_SNIFF_CMD_MSG_TYPE_ENUM`

| 值 | 名字 |
|---:|---|
| 0 | `P19051_ARC_SNIFF_RX_DHCPV4_CMD` |
| 1 | `P19051_ARC_SNIFF_RX_DHCPV6_CMD` |
| 2 | `P19051_ARC_SNIFF_DUMP_CMD` |
| 3 | `P19051_ARC_SNIFF_OBTAIN_IPV4_CLIENT_LIST_CMD` |
| 4 | `P19051_ARC_SNIFF_OBTAIN_IPV6_CLIENT_LIST_CMD` |
| 5 | `P19051_ARC_SNIFF_TOTAL_CMDS` |

### `ARC_ATDP_SPEED_TEST_MODE_TYPE`

| 值 | 名字 |
|---:|---|
| 1 | `ARC_ATDP_SPEED_TEST_TX_MODE` |
| 2 | `ARC_ATDP_SPEED_TEST_RX_MODE` |
| 3 | `ARC_ATDP_SPEED_TEST_RESET_MODE` |
| 4 | `ARC_ATDP_SPEED_TEST_OBTAIN_THROUGHPUT_MODE` |
| 5 | `ARC_ATDP_SPEED_TEST_RELAY_MODE` |
| 6 | `ARC_ATDP_SPEED_TEST_LOOPBACK_MODE` |
| 7 | `ARC_ATDP_SPEED_TEST_MAX_NO_OF_MODES` |

### `p19051_statistic_counters_s`（148 字节）

| 偏移 | 字段 |
|---:|---|
| 0 | `illegal_intf_rcv_ctr` |
| 4 | `not_arcadyan_19051_pkt_ctr` |
| 8 | `illegal_drop_pkt_ctr` |
| 12 | `tplg_discover_rx_ctr` |
| 16 | `tplg_discover_tx_ctr` |
| 20 | `tplg_notification_rx_ctr` |
| 24 | `tplg_notification_tx_ctr` |
| 28 | `tplg_notification_rx_hello_ctr` |
| 32 | `tplg_notification_tx_hello_ctr` |
| 36 | `tplg_query_rx_ctr` |
| … | 其余查询/响应/链路度量计数器 |

---

## 11. 怎么用这些结构

- **解码 1905 抓包**：按 `Cmdu_Header` 读 messageType，
  再按 TLV 的 `tlvType/tlvLength` 遍历；
- **识别 Arcadyan 私有 TLV**：31 / 35 / FUTURE_EXTENSION_01；
- **写模拟器**：按上面的偏移直接打包/解包；
- **调试**：`/dev/ATDP_CDRV` 的 ioctl 收发原始帧，配合这些结构解析。

---

## 12. 证据索引

| 内容 | 位置 |
|---|---|
| DWARF | `drv_atdp.ko`（未 strip，`readelf --debug-dump=info`） |
| 结构名 | `Cmdu_Header_t`、`AlMacAddressType_TLV_t`、`ARC_vSpf_31/35`、`FUTURE_EXTENSION_01`、`RxLinkMetric_TLV_t`、`LinkMetric_TLV_t` |
| 打包/解包 | `arc_pack_VendorSpecific_TLV_tx`、`arc_decode_VendorSpecific_TLV_tx` |

---

## 13. 附录：`p19051_device_type`（拓扑设备记录，11308 字节）

这是 `drv_atdp.ko` 里保存的**单个 1905 设备记录**，DWARF 直接给出：

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | `state` |
| 1 | u8 | `queryState` |
| 2 | u8 | `Dev_Property` |
| 3 | u8 | `Master` |
| 4 | u8[6] | `DeviceId` |
| 10 | u8 | `keep_alive_counter` |
| 12 | u32 | `DeviceId_OUI` |
| 16 | u32 | `DeviceId_Non_OUI` |
| 20 | 28B | `msgID` |
| 48 | u32 | `Version` |
| 52 | u32 | `LastChanged` |
| 56 | u32 | `InterfaceNumberOfEntries` |
| 60 | u32 | `BridgingTuplesNumberOfEntries` |
| 64 | char[32] | `friendlyName` |
| 96 | `interface_list[12]` | 每个接口的记录（10752 字节） |
| 10752 | `bridging_tuple_list[2]` | 桥接元组（224 字节） |
| 10976 | `available_lintf[12]` | 可用本地接口 |
| 11120 | `query_intf_list` | 查询中的接口 |
| 11196 | u32 | `topologylnkMetricRetryCount` |
| 11200 | u32 | `topologyQueryRetryCount` |
| 11204… | — | 各接口的 Link_Result / MAC / RSSI / DataRate / link_rate |
| 11304 | u8 | `hop_count` |

> 这个结构就是 OWL/1905 拓扑在**内核里的数据库记录**：
> 每个邻居设备一条，包含 12 个接口的链路状态与速率。
