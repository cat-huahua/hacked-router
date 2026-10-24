# Singtel Mesh Router 的 LAN 主机表与 WiFi Insight

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`pc_list*`、`vis-*`（Broadcom WiFi Insight）
> 一句话：**`pc_list` 管 LAN 主机名，`vis` 管无线诊断数据（本地 JSON/DB，不上云）。**

---

## 1. LAN 主机表：`pc_list`

### 组件

| 文件 | 作用 |
|---|---|
| `/usr/sbin/pc_list_daemon` | 守护进程，汇总 DHCP 租约 + STB 信息 |
| `/usr/sbin/pc_list_cli` | 命令行：打印/添加/删除主机名 |
| `libpclist.so.0.1` | 库 |

### 数据来源

```
/tmp/pc_list_tmp                临时汇总
/data/dhcpd_stb_info.txt        IPTV 机顶盒
dnsmasq DHCP 租约
```

`pc_list_daemon` 的字符串：

```
dhcp lease: IP[%s], MAC[%s], Name[%s], End Date[%s], Active:%d
  client-hostname "
```

### `pc_list_cli` 用法

```
Usage:  pc_list_cli print
        pc_list_cli add <mac>(format:xx:xx:xx:xx:xx:xx) <name>
        pc_list_cli del <mac>(format:xx:xx:xx:xx:xx:xx)
```

即：

```sh
pc_list_cli print
pc_list_cli add aa:bb:cc:dd:ee:ff "客厅电视"
pc_list_cli del aa:bb:cc:dd:ee:ff
```

手动名字通过 `libumng` 写 `/etc/config/pc_list_save` 的 `manual_name` section。
共享二进制表是 `/tmp/pc_list`，256×`0x218` 字节；落盘格式、字段偏移和 NAT 同步函数见
[pc_list 内部](singtel-pc-list-internals.md)。

---

## 2. WiFi Insight：`vis-*`

这是 Broadcom 的 **WiFi Insight / Visualization** 组件，纯本地诊断：

| 文件 | 作用 |
|---|---|
| `/bin/vis-dcon` | 数据集中器（data concentrator），写 `/tmp/db/visdata.db` |
| `/bin/vis-datacollector` | 采集 RRM/STA/信道数据 |
| `/usr/sbin/vis-cli` | 命令行查询 |
| `libwlvisualization.so` | 库 |

### `vis-dcon` 收集的字段

```
BSSID / SSID / STAMAC / AKM
Channel Capacity
Channel Interference
AMPDU stats
Adjacent channels
```

数据库：

```
/tmp/db/visdata.db
```

### `vis-datacollector`

```
RRM report（802.11k）
STA stats
Channel Load report
/tmp/vis-xml-%s
/tmp/vis-xml.xml
```

### `vis-cli` 用法

```
Usage: vis-cli -r [request] -o [output]
       vis-cli -b [band] [--chcapacity] -o [output]

 --chcapacity   --Channel Capacity (default: "Site Survey")
```

请求是 **URL 编码的 key=value**，例如：

```
Req=SetConfig&Interval=5&DBSize=2&StartStop=%d&Total=3
    &graphname%5B%5D=Channel+Statistics
    &graphname%5B%5D=Chanim+Statistics
    &graphname%5B%5D=Rx+CRS+Glitches
    &OverWriteDB=1&AutoStart=0&WeekDays=0&FromTm=0&ToTm=0

Req=GetBands
Req=ChannelCapacity&DutMac=<MAC>&FreqBand=<band>
```

输出是 JSON（`{ "Channel": ... }`）。

例子（在设备 shell 上）：

```sh
vis-cli -r 'Req=GetBands' -o /tmp/bands.json
vis-cli -b 5g --chcapacity -o /tmp/chcap.json
```

---

## 3. 数据去向

- `pc_list`：只在本地（DHCP 租约 + `/data/dhcpd_stb_info.txt`）；
- `vis`：写 `/tmp` 下的 DB/XML/JSON，**没有看到上传到云端的字符串**；
- 云端代理（EmbedUR）另有自己的 `chanim_stats` / `speedtest` / `pingtest`，
  和 `vis` 是两套东西。

---

## 4. 安全观察

1. `/tmp/db/visdata.db`、`/tmp/vis-xml.xml` 在 tmpfs 上，本机可读；
   里面含 **客户端 MAC / SSID / BSSID / 信号**，属于隐私数据。
2. `pc_list` 的手动名字也含 MAC ↔ 人名/设备名映射。
3. 两者都**没有云端上传证据**；但通过设备 shell 可以直接读。
4. `vis-cli` 的请求是明文 key=value，没有鉴权（本地工具）。

---

## 5. 证据索引

| 内容 | 位置 |
|---|---|
| 主机表 | `/usr/sbin/pc_list_daemon`、`pc_list_cli`、`libpclist.so` |
| WiFi Insight | `/bin/vis-dcon`、`/bin/vis-datacollector`、`/usr/sbin/vis-cli` |
| 数据库 | `/tmp/db/visdata.db` |
| 采集输出 | `/tmp/vis-xml-%s`、`/tmp/vis-xml.xml` |
| 请求语法 | `vis-cli` 的 `Req=...` 字符串 |
