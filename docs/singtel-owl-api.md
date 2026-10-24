# Singtel Mesh Router 的 OWL 本地 HTTP API

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/sbin/owl`、`/usr/sbin/owl_monitor`、`/sbin/owl-tplg`、
> `libArcOWLcore.so` / `libArcOWLapi.so` / `libArcOWLhttpApi.so`、
> `/etc/arcOwl/config.owl`
> 一句话：**OWL（SON）在设备上开了一个本地 HTTP JSON 接口，
> `/sbin/owl-tplg` 用 `wget http://127.0.0.1:55761/status/tplg` 读拓扑。**

---

## 1. 组件

| 组件 | 作用 |
|---|---|
| `/usr/sbin/owl` | OWL 主程序（`libmicrohttpd` + `libjson-c`） |
| `/usr/sbin/owl_monitor` | 监视/拉起 |
| `/sbin/owl-tplg` | 用 wget 读 `/status/tplg`，拼拓扑树 |
| `libArcOWLcore.so` | 核心：拓扑、band steering、channel load、LED、固件同步 |
| `libArcOWLapi.so` | 系统侧 API（midcore、WLAN、DHCP leases） |
| `libArcOWLhttpApi.so` | HTTP 客户端（`owl_http_get` / `owl_http_post`） |
| `libArcShareATDP.so` + `drv_atdp.ko` | 1905/ATDP 传输层 |

---

## 2. 本地 HTTP 端点

从 `libArcOWLcore.so` 的字符串里能直接看到：

```
/status/DevInfo
/status/MasterInfo
/status/NetworkTime
/status/stainfo
/status/Wificonfig
/status/tplg
```

| 路径 | 内容（推断自字段名） |
|---|---|
| `/status/DevInfo` | 设备信息（型号/版本/序列号） |
| `/status/MasterInfo` | 主节点信息 |
| `/status/NetworkTime` | 网络时间 |
| `/status/stainfo` | 客户端（station）信息 |
| `/status/Wificonfig` | WiFi 配置/信道 |
| `/status/tplg` | **拓扑树**（device_name/device_id/parent_id/connect_type） |

`/sbin/owl-tplg` 的实际用法：

```sh
wget http://127.0.0.1:55761/status/tplg -O - > /tmp/dev-info
# 解析 device_name / device_id / parent_id / connect_type
```

> 端口 **55761** 是 `owl-tplg` 里写死的；`config.owl` 里另有
> `HDM_APP_PORT 55661`、`SOCKET_PORT 7788`，属于其他通道，别混用。

`libArcOWLhttpApi.so` 提供：

```
owl_http_get
owl_http_post
GET %s HTTP/1.0
POST %s HTTP/1.0
Content-Type: application/json
```

即 **HTTP/1.0 + JSON**。

---

## 3. `config.owl` 参数（出厂）

```c
OWL_INFORMATION {
    OWL_CONFIG_IN_FLASH 1;
    OWL_DATA_TRANSMISSION_MODE 1;   // 1=1905.1, 2=socket
    OWL_WAN_INTERFACE eth0.10;
    OWL_DEV_INTERFACE eth1;
    OWL_ETH_INTERFACE br0;
    OWL_MAIN_LOOP_TIME 60;
    OWL_MASTER_REQUEST_DELAY_TIME 3;
    OWL_DEBUG_LEVEL 0;
}
WIFI_INFORMATION {
    INTERFACE_2.4GHz wl1;
    INTERFACE_5GHz wl0;
    SON_DELAY_TIME 1;
    ROAMING_SIGNAL -70;
    CHANNEL_OVERLOAD_2.4GHz 70;
    CHANNEL_OVERLOAD_5GHz 70;
    THRESH_2G -55;
    THRESH_5G -80;
    RSSI_LOW -70;
    STEER_PROHIBIT 300;
    BLACKLIST_EXPIRE 3600;
    BTM_BLACKLIST_EXPIRE 3600;
}
HDM_INFORMATION {
    HDM_APP_PORT 55661;
    HDM_DISCOVER_KEYWORD HDM3596OWL_TS;
}
```

这些值决定 band steering 的阈值与禁 steer 时间。

---

## 3.1 本地拓扑守护：`arc_tplgd`

`/tmp/arc_tplg_path` 是拓扑守护进程的本地命令通道。`arc_tplgd` 的数据来源：

```
/tmp/dhcpd.leases        DHCP 租约
/tmp/etc/dhcpd.leases
/tmp/dhcp_mac.txt        MAC 列表
/tmp/nbt_XXXXXX          NetBIOS 扫描结果
/tmp/.ssdp_devices       SSDP 设备
nbtscan -q -t 300 <网段>  ← 用 NetBIOS 补主机名
```

它还会写：

```
mngcli tmp_set TMP_WBD_TPLG_CCNum=%d
```

`arc_tplg_cli` 通过 `/tmp/arc_tplg_path` 查询/触发拓扑。

> **注意**：这里的 `tplg` 是 **topology（拓扑）**，不是“template（模板）”。
> 它和 OWL 的 `/status/tplg` 是同一份拓扑数据的不同入口。

---

## 4. Band steering（从字符串还原）

`libArcOWLcore.so` 里的日志直接写出了决策原因：

```
Start Steering : [MAC] Mode= BTM Reason=2G Channel OverLoad(2G->5G) Channel_Load=%d
Start Steering : [MAC] Mode= BTM Reason=5G Channel OverLoad(5G->2G) Channel_Load=%d
Start Steering : [MAC] Mode= BTM Reason=RSSI High, 2G->5G RSSI=%d
Start Steering : [MAC] Mode= BTM Reason=RSSI Low, 5G->2G RSSI=%d
Start Steering : [MAC] Mode= BTM Reason=RSSI LOW in 2G, AP Roaming ...
Start Steering : [MAC] Mode= Legacy Reason=...
```

两种模式：

- **BTM**（802.11v BSS Transition Management）—— 现代客户端；
- **Legacy** —— 老客户端（靠 deauth/黑名单）。

状态文件：

```
/data/SteeringEvent_All
/tmp/steering_record
```

配置键：

```
ARC_OWL_steer_capability
ARC_OWL_Steer_prohibit
ARC_OWL_WIFI_CONFIG_STEER_CAPABILITY
ARC_OWL_WIFI_CONFIG_STEER_PROHIBIT
ARC_OWL_WIFI_CONFIG_CHANLOAD_REPORT
ARC_OWL_ChanLoad_Report_t
```

---

## 5. 拓扑与 LED

- 拓扑节点字段：`device_name`、`device_id`、`parent_id`、`connect_type`；
- LED 上报：`"%02X:%02X:%02X:%02X:%02X:%02X_leds":{...}`；
- `owl -report ap|led|sta` 会把对应数据上报给 master；
- 固件同步：`/owl/owl_image.bin`、`/etc/RE_FW/MTDDATA`、
  `/answer_machine/MTDDATA`。

---

## 6. App 控制面（从字符串看）

`libArcOWLcore.so` 里有这些“APP-”日志：

```
APP-Failed to change admin password by %s
APP-Failed to change network name and password by %s
APP-Failed to check FW upgrade by %s
APP-Failed to pause Internet by %s
APP-Failed to rename the disc %s by %s
APP-Failed to resume Internet by %s
APP-FW download requested by %s was failed
APP-FW download was cancelled by %s
APP-Password check by %s was failed
```

说明 OWL HTTP API 还负责：

- 改管理密码；
- 改 WiFi 名称/口令；
- 暂停/恢复上网（parental control / internet pause）；
- 重命名 disc（节点）；
- 固件升级检查/下载。

---

## 7. 证书/鉴权

字符串里有：

```
client_cert=NULL
Failed to import client certificate
Client certificate not trusted or invalid
client_cert_status = %lu
gnutls_x509_crt_import
```

说明 OWL 的 HTTP 服务端会看**客户端证书**，用于区分普通请求和 App 控制请求。
本机 `wget`（没有客户端证书）能读 `/status/tplg`，但改配置类接口很可能需要证书。

---

## 8. 怎么在设备上读拓扑

```sh
# 设备 shell 上
wget -qO- http://127.0.0.1:55761/status/tplg
owl-tplg          # 直接打印树
owl -report ap    # 让 master 上报 AP 数据
```

`owl-tplg` 的输出示例（格式）：

```
客厅节点 (AA:BB:CC:DD:EE:FF, GE)
|-- 卧室节点 (11:22:33:44:55:66, N2G)
```

---

## 9. 观察与风险

1. **本地 HTTP 无 TLS**：`http://127.0.0.1:55761`，只绑本地，但本机任何进程可读。
2. **App 控制面**：改密码、暂停上网、固件升级都能通过 OWL 触发；
   是否有客户端证书校验、校验强度如何，还没逐函数确认。
3. **band steering 阈值**在 `config.owl` 里，改它可以直接影响客户端被踢的行为。
4. **固件同步** `owl_image.bin` + `MTDDATA` 是另一条升级链（mesh 节点间同步），
   和 `fw_upgrade` 的整机升级不是一回事。

---

## 10. 还没解的

- 每个 `/status/*` 端点的完整 JSON schema（只确认字段名）。
- OWL HTTP 的鉴权流程（客户端证书如何签发/校验）。
- `/owl/owl_image.bin` 的容器格式。
- `libArcOWLcore.so` 里 1905 消息与 HTTP 的映射细节。

---

## 11. 证据索引

| 内容 | 位置 |
|---|---|
| 端点 | `libArcOWLcore.so`：`/status/DevInfo` 等 |
| 拓扑读取 | `/sbin/owl-tplg`（`127.0.0.1:55761/status/tplg`） |
| HTTP 客户端 | `libArcOWLhttpApi.so`（`owl_http_get/post`） |
| 配置 | `/etc/arcOwl/config.owl` |
| Band steering | `libArcOWLcore.so` 日志字符串、`/data/SteeringEvent_All` |
| 固件同步 | `/owl/owl_image.bin`、`/etc/RE_FW/MTDDATA` |
