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

## 9. 怎么用这些结构

- **解码 1905 抓包**：按 `Cmdu_Header` 读 messageType，
  再按 TLV 的 `tlvType/tlvLength` 遍历；
- **识别 Arcadyan 私有 TLV**：31 / 35 / FUTURE_EXTENSION_01；
- **写模拟器**：按上面的偏移直接打包/解包；
- **调试**：`/dev/ATDP_CDRV` 的 ioctl 收发原始帧，配合这些结构解析。

---

## 10. 证据索引

| 内容 | 位置 |
|---|---|
| DWARF | `drv_atdp.ko`（未 strip，`readelf --debug-dump=info`） |
| 结构名 | `Cmdu_Header_t`、`AlMacAddressType_TLV_t`、`ARC_vSpf_31/35`、`FUTURE_EXTENSION_01`、`RxLinkMetric_TLV_t`、`LinkMetric_TLV_t` |
| 打包/解包 | `arc_pack_VendorSpecific_TLV_tx`、`arc_decode_VendorSpecific_TLV_tx` |
