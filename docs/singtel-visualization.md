# Singtel 的 WiFi Insight（Broadcom `visualization`）数据链

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/bin/vis-dcon`、`/bin/visdata`、`/bin/vis-datacollector`、
> `/usr/sbin/vis-cli`、`/usr/lib/libwlvisualization.so`、`/sbin/arc_visualization`
> 一句话：**这是 Broadcom BSP 的 `visualization` 组件（WiFi Insight）：
> 从 dhd 驱动 iovar 采数据 → 存进 SQLite → 出 JSON/XML 给网页画图。**

---

## 1. 组件与启动

```
/sbin/arc_visualization boot
        ├─ vis-dcon            ← dataconcentrator，本地 SQLite 服务端
        └─ vis-datacollector   ← 采集器，把驱动数据发给 vis-dcon

/usr/sbin/vis-cli              ← 命令行前端（vis_do_json_get/set）
/bin/vis-dcon                  ← 同名服务端（dataconcentrator）
/bin/visdata                   ← RRM/802.11k 报告处理 + XML 中转
```

`libwlvisualization.so` 提供 `vis_do_json_get` / `vis_do_json_set`，
`vis-cli` 只是它的壳：

```
Usage: vis-cli -r [request] -o [output]
       vis-cli -b [band] [--chcapacity] -o [output]
 -r  --request string
 -o  --output file
 -p  --print results
```

**编译路径泄漏**（`vis-dcon` 的 `.debug_str`）：

```
.../broadcom-bsp-5.02L03/bcmdrivers/broadcom/net/wl/impl32/main/
    components/apps/visualization/dataconcentrator
.../targets/WG9116AEAC23-ST/fs.build/public/include/json-c
```

即：**Broadcom BSP 5.02L03 的原生 visualization 组件，Arcadyan 只做了 target 适配**，
并额外加了 json-c / libxml2。

---

## 2. 数据源（驱动侧）

| 来源 | 证据 |
|---|---|
| chanim stats（信道占用） | `wl_check_chanim_stats_list`、`VIS-CHANIM >> ... chanspec tx inbss obss nocat nopkt doze txop goodtx badtx glitch badplcp knoise idle` |
| per-STA 计数 | `wl_counters`、`wlcntver11t_to_wlcnt...`（多版本 counter 结构转换） |
| STA info | `wl_wl_get_sta_info`、`ERROR: unknown driver station info version %d` |
| scan（邻居 AP） | `wl_dump_networks`、`bss_info_version` 版本检查 |
| 802.11k RRM | `parse_channel_load_report`、`parse_sta_stats_report`、`get_rrm_report_from_queue` |
| chanspec 转换 | `wl_chspec_from_legacy`、`wl_chspec_from_driver` |

> 采集器对版本很敏感：`Version mismatch, please upgrade. Got %d, expected %d or 1`。
> 这说明它是**按驱动结构体版本**解析的，跨固件版本不能直接复用。

---

## 3. 存储：SQLite

```
/tmp/db/visdata.db        ← 数据库（tmpfs，重启即丢）
/tmp/vis-xml.xml          ← XML 中转
/tmp/vis-xml-%s           ← 按接口/进程的 XML 临时文件
```

**证据**：`GetDBFile`、`create_directory`、`create_database_and_tables`、
`DB SIZE : %d`、`Failed to Save to DB`。

建表语句是**格式串**，表名/列名运行时拼：

```c
CREATE TABLE IF NOT EXISTS %s(%s INTEGER PRIMARY KEY AUTOINCREMENT,
    %s INTEGER, %s TEXT, ... );
CREATE TABLE IF NOT EXISTS %s( %s INTEGER, %s INTEGER, ... );
DELETE FROM %s WHERE %s IN (SELECT DISTINCT %s FROM %s ORDER BY %s ASC LIMIT %d);
```

字符串里能直接确认的表名：

```
dutlist        dutdetails      graphs      config
```

其余表名在运行时从 `get_all_tablenames()`（查 `sqlite_master`）拿到，
所以二进制里没有完整清单 —— 这一点如实记录，不猜。

相关函数：

```
create_database_and_tables   create_graphs_table   get_all_tablenames
get_dut_details_from_db      get_all_duts_from_db
get_graphs_list_from_db      get_chanim_from_db
get_stastats_from_db         get_adv_sta_stats_from_db
get_ampdu_stats_from_db      get_channel_capacity_from_db
get_networks_from_db         get_config_from_db
delete_rows_from_tables      execute_sql_statement
get_pragma_value             get_graph_row
```

---

## 4. 关键结构体（DWARF 精确布局）

`vis-dcon` 带 `debug_info`，以下直接来自 `readelf --debug-dump=info`。

### `assoc_sta`（84 字节，单个关联 STA 的统计）

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u32 | version |
| 4 | u32 | length |
| 8 | s32 | rssi |
| 12 | s32 | phyrate |
| 16 | u8[20] | mac |
| 36 | u32 | prequested |
| 40 | u32 | pstored |
| 44 | u32 | pdropped |
| 48 | u32 | pretried |
| 52 | u32 | putilization |
| 56 | u32 | pqlength |
| 60 | u32 | prtsfail |
| 64 | u32 | prtrydrop |
| 68 | u32 | ppsretry |
| 72 | u32 | packed |
| 76 | float | ptput |
| 80 | float | pphyrate |

`assoc_sta_list`（96 字节）：`version / length / timestamp / sta[1]`。

### `counters_t_`（16 字节）

| 偏移 | 字段 |
|---:|---|
| 0 | timestamp |
| 4 | rxcrsglitch |
| 8 | rxbadfcs |
| 12 | rxbadplcp |

### `congestion_t_`（72 字节，chanim 一行）

| 偏移 | 字段 | 偏移 | 字段 |
|---:|---|---:|---|
| 0 | channel | 36 | badtx |
| 4 | tx | 40 | glitchcnt |
| 8 | inbss | 44 | badplcp |
| 12 | obss | 48 | knoise (s8) |
| 16 | nocat | 49 | chan_idle (u8) |
| 20 | nopkt | 52 | busy |
| 24 | doze | 56 | availcap |
| 28 | txop | 60 | wifi |
| 32 | goodtx | 64 | nonwifi |
| | | 68 | timestamp |

### `dut_info_t_`（348 字节，扫描到的邻居设备）

| 偏移 | 字段 |
|---:|---|
| 0 | isenabled |
| 4 | channel |
| 8 | ctrlch |
| 12 | rowid |
| 16 | isAP |
| 20 | bandwidth |
| 24 | band |
| 28 | noise |
| 32 | rssi |
| 36 | maxrate |
| 40 | bssid (18B) |
| 58 | ssid (129B) |
| 187 | mac (18B) |
| 205 | stamac (18B) |
| 223 | networktype (8B) |
| 231 | mcastrsntype (10B) |
| 241 | ucastrsntype (50B) |
| 291 | akmrsntype (53B) |
| 344 | errinfo |

### `ap_info_t_`（296 字节）

`bssid(18) / ssid(130) / rssi / noise / channel / ctrlch / band /
bandwidth / maxrate / networktype(8) / mcastrsntype(10) / ucastrsntype(50) / akmrsntype(52)`

### `channel_map_t_`（148 字节）

`ssid[132] / ctrlch / channel / bandwidth / rssi`

### 其它（同文件）

```
channel_maplist_t_   152    congestion_list_t_  80    dut_list_t_    356
graphs_t_             20    graphdetails_t_    108    graph_list_t_   48
graphname_t_         376    graphnamelist_t_   380    networks_list_t_ 308
packet_header_t_     396    table_t_           156    tablelist_t_    164
records_to_fetch_t_   72    iovar_handler_t_    36    mutexes_t_       32
vis_rrm_stats_t_      52    vis_sta_stats_t_    40    tx_ampdu_t_      92
```

> `dut_list_t_` / `networks_list_t_` / `graph_list_t_` 是「数组 + length」的
> 变长结构，解 SQLite 或抓 socket 时按 `length` 遍历即可。

---

## 5. 图表（graph）模型

`graphs` 表 + `EnabledGraphs` 控制开关。字符串里的图名：

```
Chanim Statistics          Channel Capacity
AMPDU Statistics           Air Time Opportunity
ChannelStats               AMPDUStats
AMPDU RX/TX With SGI       AMPDU RX/TX Without SGI
AMPDU RX/TX VHT With SGI   AMPDU RX/TX VHT Without SGI
CHANIMSTATSFORMETRICS      AdvancedPerStationDetails
```

JSON 生成函数：

```
add_json_header / add_json_graph_header / add_json_for_graph_data
add_bargraph_details / add_graph_header_details / get_json_for_graphs
create_all_channels_json_data / add_channel_capacity_to_json
add_channel_interference_to_json / add_adjacent_channels_to_json
add_ampdu_stats_to_json / add_sta_adv_rrm_stats(_acked)
```

信道容量按 20/40/80 MHz 分别算：

```
add_channel_capacity_for_twenty / _fourty / _eighty
add_interference_for_twenty / _fourty / _eighty
get_maximum_availcap / get_maximum_nonwifi_interference
```

---

## 6. nvram 键

```
vis_daemon
vis_dcon_ipaddr            ← 服务端地址（默认 127.0.0.1）
vis_do_remote_dcon         ← 是否连远端 dcon
vis_debug_level
vis_pscan
```

`vis-dcon` 是**本地服务端**：`create_server` / `accept` / `client_handler` /
`recv_data` / `send_data`；`vis-datacollector` 侧是 `connect_to_server`。
日志格式：

```
VIS-SOCK >> %s : Server = %s	 port = %d
VIS-SOCK >> %s : Failed to Connect to server : %s Port : %d
```

> **端口常量没有在字符串里出现**，是编译进代码的整数；
> 想精确拿到需要对 `connect_to_server` 做反汇编（本机没有 ARM objdump，
> 用 r2 可以，但这次没做，如实留作未解）。

---

## 7. 网页侧：页面在、后端不在

- `www/channel_capacity.htm`、`www/js/custom/wifi_insight.js`、
  `www/js/custom/channelcapacity.js`、`www/css/visstyle.css` 都在。
- 前端请求的端点：

```js
gURLBands = 'http://localhost/getallbands.php';
CGIs = ["recommend_action"];
json.cgi
```

- **但 rootfs 里没有 `www/getallbands.php`，也没有 `www/cgi/json.cgi`。**

这和之前枚举配置键时发现的 `ARC_HTTPD_JSONAPI_Enable=0`、`json.cgi` / `/api/`
是同一件事：**WiFi Insight 的网页壳保留了，后端被裁掉/关闭**。
所以这个功能在本固件上实际不可用（除非手工补上后端并打开开关）。

---

## 8. 安全与隐私观察

1. **数据库在 tmpfs**（`/tmp/db/visdata.db`）：重启即清，
   但运行期包含**邻居 AP 的 BSSID/SSID/RSSI** 和**本网客户端的 MAC/流量统计**。
2. **默认只连 127.0.0.1**；`vis_do_remote_dcon` 若被置 1，
   采集数据会发到 `vis_dcon_ipaddr` 指向的主机 —— **这是一个潜在的数据外发开关**。
3. `vis-cli` 是本地命令行，能直接读 JSON；只要有 shell 就能取全部统计。
4. 采集器按驱动结构体版本解析，**版本不匹配就打印并丢弃**，不会崩。
5. `visdata` 处理 802.11k RRM 报告时会把原始报文写 `/tmp/vis-xml-*`（tmpfs）。

---

## 9. 证据索引

| 内容 | 位置 |
|---|---|
| 启动脚本 | `/sbin/arc_visualization` |
| 采集/服务端 | `/bin/vis-dcon`（自带 DWARF）、`/bin/vis-datacollector` |
| RRM/XML | `/bin/visdata`（自带符号） |
| JSON 前端 | `/usr/sbin/vis-cli` → `libwlvisualization.so`（`vis_do_json_get/set`） |
| 数据库 | `/tmp/db/visdata.db`；`CREATE TABLE IF NOT EXISTS %s(...)` |
| 结构体 | `readelf --debug-dump=info vis-dcon`：`assoc_sta`、`dut_info_t_`、`congestion_t_`、`channel_map_t_` |
| 图名 | `Chanim Statistics`、`AMPDU Statistics`、`Air Time Opportunity`、`CHANIMSTATSFORMETRICS` |
| 网页 | `www/channel_capacity.htm`、`www/js/custom/wifi_insight.js` |
| 缺失的后端 | `www/cgi/json.cgi`、`www/getallbands.php` 均不存在 |

---

## 10. 未解（如实记录）

- `connect_to_server` 的**端口常量**（需反汇编）。
- SQLite 的**完整 schema**：表名/列名在运行时拼，二进制里只有格式串；
  要拿全表得在设备上 `sqlite3 /tmp/db/visdata.db .schema`。
- `vis-dcon` 与 `vis-datacollector` 之间的**私有协议格式**（不是 HTTP；
  只有 `create_server/accept/recv_data/send_data` 这一层）。
- `visdata` 与 `vis-dcon` 如何交接 XML（`send_xml_data` 的目标 socket）。
