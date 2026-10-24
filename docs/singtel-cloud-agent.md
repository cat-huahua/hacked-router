# Singtel Mesh Router 里的 **EmbedUR 云管理代理**

> 设备：Singtel Mesh Router（Arcadyan WG9116AEAC23-ST，v5.02.00 build09b）
> 材料：`WE410443-ST_v6.02.00_build14.trx` 解出的 UBIFS rootfs
> 日期：2026-10-17

---

## 0. 一句话结论

固件里藏着一整套**第三方云管理代理**（EmbedUR eRM），**默认开启**：

```
/usr/bin/embedur/erm_agent.tar.bz2   2.7 MB
  └─ 运行时解到 /tmp/erm，安装到 /data/embedur
       └─ rrm_bcm_arm -r -O Singtel -i mqtt.wifi-analytics.singnet.com.sg
```

它用 **MQTT over TLS** 连 Singtel 的云端，能**改 WiFi、踢客户端、换信道、重启、刷固件**，
而且**固件里带着与生产 broker 证书配对的私钥**（详见 §9）。

这同时回答了 `mqtt_spy/` 那条一直没解开的线：**我们以前猜的 topic 结构是对的**，
客户端实现就在这份 rootfs 里（当时以为它在 extender 的加密 rootfs 里）。

---

## 1. 它是怎么被拉起来的

配置里有个开关，**出厂就是 1**：

```
ARC_3rd_EmbedUR_Enable=1
```

`/sbin/arc_embedur`（shell）在 boot 时执行：

| 步骤 | 做什么 |
|---|---|
| 1 | 如果 `/data/embedur/erm_agent.tar.bz2` 存在，**优先用它**（云端可以推新版下来） |
| 2 | 否则用固件里的 `/usr/bin/embedur/erm_agent.tar.bz2` |
| 3 | 解到 `/tmp`，把 `erm_agent` 改名成 `erm_agent_runtime` |
| 4 | `ln -s /tmp/erm_agent_runtime /tmp/erm` |
| 5 | 跑 `/tmp/erm/start_erm` |

`start_erm` 再做：

```sh
. /tmp/erm_config/erm_config            # 或 /data/embedur/erm_config_override
[ -f /tmp/erm/mosquitto ] && mosquitto -d -p 1883 -c /tmp/erm/mosquitto.conf
/tmp/erm/systematic_reboot_collect arcadyan &
/tmp/erm/erm_watchdog &
while [ 1 ]; do
    /tmp/erm/rrm_bcm_arm $CMDLINE_EXTRA -i $SERVER -L /tmp/erm_log
    mv /tmp/erm_log /tmp/erm_log_restart
    sleep 1
done
```

`rrm_bcm_arm` 挂了会**无限重启**；`erm_watchdog` 再罩一层。

---

## 2. 包结构（解包后逐项确认）

```bash
cp /usr/bin/embedur/erm_agent.tar.bz2 /tmp && cd /tmp
tar xjf erm_agent.tar.bz2 && ls erm_agent
```

| 文件 | 大小 | 作用 |
|---|---:|---|
| `rrm_bcm_arm` | 2.2 MB | ★ 主程序：MQTT 客户端 + RRM（射频资源管理）+ 命令处理 |
| `broadband_ssl` | 1.6 MB | 宽带测速 / 连通性检测（DNS/HTTP/HTTPS/PING） |
| `image_manager` | 879 KB | 固件升级：MD5 + 签名校验 + 解密 |
| `wlu_all` | 497 KB | Broadcom `wl` 工具集（改无线参数） |
| `dhcp_scan` | 203 KB | 用 libpcap 抓 DHCP，发现 LAN 客户端 |
| `speedtest` / `pingtest` | 32 / 14 KB | 测速与延迟 |
| `chanim_stats` | 9 KB | 读 Broadcom 信道干扰统计 |
| `systematic_reboot.sh` | 9.8 KB | 自动重启的日志收集 |
| `erm_watchdog` | 14 KB | 看门狗 |
| `libjansson.so.4` | 177 KB | JSON 库 |
| `arc_embedur` | 1.3 KB | 开机启动脚本（与 `/sbin/arc_embedur` 同源） |
| `start_erm` | 1.6 KB | 启动器 |
| `erm_config` / `erm_config_staging` | 83 / 64 B | 生产 / 测试环境配置 |
| `ca-prod.crt` / `ca-staging.crt` | 1.2 / 1.1 KB | 证书（见 §9） |
| `mqtt-key*.pem` | 1.7 KB ×3 | **私钥**（见 §9） |
| `mqtt-cert*.pem` | 1.2–1.3 KB | TLS 信任根 |
| `sig_key.pub` | 451 B | 固件镜像签名公钥 |
| `version` | 14 B | `2.3.29.1-0301` |
| `model` | 5 B | `0301` |

`strings rrm_bcm_arm` 里还能看到构建路径：

```
/data/<user>/jenkins/workspace/workspace/SMR-2.3.29-memleak/build/arcadyan_mesh/...
/home/<user>/crosstools-gcc-5.5-.../buildroot-2017.11.1/.../glibc-2.26
```

`SMR` = Singtel Mesh Router；工具链 GCC 5.5 / glibc 2.26 / Linux 4.1。

---

## 3. 生产 / 测试两套环境

`erm_config`：

```sh
SERVER=mqtt.wifi-analytics.singnet.com.sg
CMDLINE_EXTRA="-r -O Singtel"
```

`erm_config_staging`：

```sh
SERVER=118.201.155.242
CMDLINE_EXTRA="-r -O Singtel"
```

**切换方式**（都是 root 脚本，不需要重新刷机）：

```sh
# 去测试环境
cp /tmp/erm/erm_config_staging /data/embedur/erm_config_override
sync; reboot

# 回生产
rm /data/embedur/erm_config_override
sync; reboot
```

`/data/embedur/erm_config_override` 是**持久化**的 —— 一旦被改成测试环境，
恢复出厂前都会一直连 `118.201.155.242`。

---

## 4. ★ MQTT 主题：确认了 `mqtt_spy` 的观察

`rrm_bcm_arm` 里的主题模板（`strings | grep` 可直接看到）：

```
devices/%s/adornment        ← 装饰 / LED / 状态
devices/%s/%s               ← 第二段是 desired_state / direct / image
devices/data/%s             ← 上报数据（shadow）
groups/%s/desired_state     ← 分组（mesh）配置
%s/gateway_state            ← 网关状态
```

**订阅列表是静态反汇编确认的**，不是猜的：

| 函数地址 | 作用 |
|---|---|
| `0x59A04` | 拼接主题：`snprintf(buf, 0x80, "devices/%s/%s", device_id, suffix)` |
| `0x59E68` | 依次注册 `desired_state`、`direct` |
| `0x771FC` | 注册 `adornment` |
| `0x70494` | 注册 `image`（**固件升级**） |
| `0x59A04` 内 `0x55CB4` 分支 | 非 Singtel 部署走 Jio 主题分支 |

所以设备**订阅**：

```
devices/<id>/adornment
devices/<id>/desired_state
devices/<id>/direct
devices/<id>/image          ← 之前抓包没看到的那一条
```

并**发布**到 `devices/data/<id>`（状态/shadow）和 `<gateway_topic>/gateway_state`。

> 这也解释了为什么之前拿 `desired_state` 发命令“零反应”：
> **topic 对了，但 payload 必须是云端那套 JSON**，不是 `?$[+` 分隔符。
> 现在 `image` 这条也确认了 —— 云端可以远程推固件。

同一份二进制还带着 **Jio（印度）部署** 的主题，说明它是一套多运营商通用代理：

```
jioiot/svcf/accesspoint/%012llX/UC/rev/cmd
jioiot/svcf/accesspoint/%012llX/UC/rev/cmd/ack
jioiot/svcf/accesspoint/%012llX/UC/fwd/alerts
jioiot/svcf/accesspoint/%012llX/UC/fwd/locinfo
```

这和之前用假 broker 抓到的 `devices/<MAC>/adornment`、
`devices/<MAC>/desired_state`、`devices/<MAC>/direct`、`devices/data/shadow`
**逐字对应**（`%s` 就是大写 MAC / device_id）。

### 消息里的字段（字符串模板）

```
{"gateway_topic":"%s"}
"adornment":%s,
"client_mac":"%012llX",
"device_id":"%012llX",
{"ap":"%s","ssid":"%s","bssid":"%s","state":%d,"timer":%d}
"timestamp":%u,
"%s":"%s" / "%s":%lld / "%s":%0.6f / "%s":true|false|null
```

还有 HTTP 形态的 provisioning 端点（本地/云侧）：

```
/accesspoint?_adornment&_device_id=%s&_sn=%s&_version=%s
/auto_reboot?_device_id=%s&_schema=common.auto_reboot_config.%s&_config
/capwap/jsondirect -s -u /v1.0/ap/gateway/%s -v ...
```

> **还没拿到的**：云端下发命令的**完整 JSON schema**（键名、嵌套、动作枚举）。
> 现在至少知道它是 **JSON over MQTT**，主题、device_id 格式、公共字段都定了；
> 下一步可以对 `rrm_bcm_arm` 做静态反汇编或 `strace` 动态跟踪。

---

## 5. 它能干什么（从字符串里能点出来的能力）

| 能力 | 证据 |
|---|---|
| **band steering**（2.4G/5G 踢客户端） | `band_steer_*`、`Active steering client from %s Ghz to %s Ghz due to RSSI/overload/MCS` |
| **802.11k/v** | `80211kv_enabled`、`80211v Blocking MAC address` |
| **自动换信道 / DFS** | `ap_auto_channel_changed`、`channel_dfs_backup`、`Adding radar channel` |
| **客户端统计** | RSSI/SNR/MCS/吞吐、`accesspoint_stats__*` |
| **AP 资源统计** | CPU / 内存 / 温度 / 存储 / WAN 吞吐 |
| **测速** | `speedtest`、`pingtest`、broadband detection（DNS/HTTP/HTTPS/PING） |
| **自动重启** | `auto_reboot_*`（见 §6） |
| **固件升级** | `image_manager`（见 §7） |
| **APP 配网** | `App Provision:`（本地 socket + JSON） |
| **家长控制** | `/data/embedur/parental_controls.json` |
| **DHCP 扫描** | `dhcp_scan`（libpcap，写 `/tmp/dhcp_<iface>_<mac>`） |
| **Mesh / Guest 配置** | 二进制里带 OpenWrt/UCI 模板：`/etc/config/mesh`、guest 网络与防火墙规则 |

注意最后一条：这台机器**不是** OpenWrt，但代理里带着 UCI 模板 —— 同一份代码
也给别的平台（sagemcom / arcadyan_mtk / edgecore / sercom / jio）用。

### 5.1 ★ 本地 App 配网协议（UDP 9995 + JSON socket）

代理不止连云端，还在**局域网**上开了一条配网通道：

```
UDP_BCAST_PORT 默认 9995
iptables -I INPUT  -p udp --dport <port> -i br0 -j ACCEPT
iptables -I OUTPUT -p udp --dport <port> -j ACCEPT
```

同一个二进制里还有 `handle_json_socket` / `app_provision.c`。反汇编确认它解析的
JSON 字段（`json_object_get` 的键）：

```
method        session_id    members       model
rest_access_info   statetype   broadband_quality
client_probe_info  enh_steer_config   enh_blacklist_config
gateway_topic      ap_mac      bssid      mac
private            eac         config     location
timestamp
```

分派逻辑里能看到两个字符串比较（`0x4E944` / `0x4E958`），
字段是 **`type` 和 `statetype`**（不是 `method`）：

```
json_object_get(json, "type")       → strcmp(type, "accesspoint") == 0
json_object_get(json, "statetype")  → strcmp(statetype, "desired_state") == 0
    ↓ 命中
json_object_get(json, "location") → strncpy → 0x3DD80("accesspoint","config","location",值)
```

也就是说：**云端和本地 App 用的是同一套 JSON 形态**，只是承载方式不同
（MQTT vs UDP/JSON socket）。这解释了为什么 `mqtt_spy` 的 topic 对了，
但发纯文本命令没反应 —— 它期待的是带 `type`/`statetype` 的 JSON 对象。

**最简的一条真实命令**：

```json
{"type":"accesspoint","statetype":"desired_state","id":"<MAC>","location":"Living Room"}
```

#### 报文外层（envelope）

同一份二进制里还有一个**构造上报报文**的函数（`0x272AC`），
它逐字段 `json_object_set_new`，可以直接读出外层结构：

```json
{
  "id": "<MAC>",
  "statetype": "runtime",
  "type": "accesspoint",
  "category": "device",
  "next_update_time": <int>,
  "timestamp": <int>,
  "device_time": <int>,
  ...
}
```

所以：

| 方向 | topic | `statetype` | 关键字段 |
|---|---|---|---|
| 设备 → 云 | `devices/data/<id>` | `runtime` | `id/type/category/timestamp/device_time/next_update_time` |
| 云 → 设备 | `devices/<id>/desired_state` | **`desired_state`** | `type=accesspoint` + `location` 等 |
| 云 → 设备 | `devices/<id>/direct` | 待确认（很可能也是 envelope） | 待确认 |
| 云 → 设备 | `devices/<id>/image` | — | 固件升级 |
| 组 | `groups/<gid>/desired_state` | `desired_state` | 组级配置 |

**一条“真正能生效”的命令长这样**（最小可用示例，改设备位置）：

```json
{
  "type": "accesspoint",
  "statetype": "desired_state",
  "id": "<设备 MAC>",
  "location": "Living Room"
}
```

发到 `devices/<MAC>/desired_state`。

> 注意：`location` 是反汇编里**唯一能确认会被写进配置**的 desired_state 字段
> （写入 `accesspoint/config/location`）。其它字段（`members`、`radio_24`、
> `radio_5`、`enh_steer_config`…）会被读出来，但具体落到哪个配置键还没有逐个确认。

### 5.2 ★ 家长控制（按 DNS 关键字拦截 + 流量配额）

配置在 `/data/embedur/parental_controls.json`，运行时会生成：

```
/tmp/parental_controls_members.sh
/tmp/parental_controls_services.sh
/tmp/parental_controls_ip_tables.sh
/tmp/parental_controls_members_ebtables.sh
/tmp/singtel_parental_controls.sh
```

核心规则（字符串里原样可见）：

```sh
iptables -t filter -N member_filters_0x<mark>
iptables -t filter -I FORWARD -m mark --mark 0x<mark>/0x<mask> -j member_filters_0x<mark>
iptables -t filter -A member_filters_0x<mark> -p udp --dport 53 \
         -m string --algo bm --icase --string '<keyword>' -j REJECT
iptables -t filter -A member_filters_0x<mark> -p tcp --dport 53 \
         -m string --algo bm --icase --string '<keyword>' -j REJECT
```

也就是说：**它不是解析 DNS，而是在 53 端口的报文里做字符串匹配**。
每个客户端按 connmark 分到自己的链（`member_filters_0x…`）。

另外还有**流量配额**：

```
PC: ... parental member test, pc_member->total_bytes:%llu  total_bytes_limit:%llu
PC: ... parental member over limit, blocking...
```

超额后同一个链直接 `-j REJECT`。这套规则是**独立的**，和 `arc_firewalld` 的
访问控制（`ARC_FIREWALL_AC_*`）不是一回事。

### 5.3 测量组件（测速 / 延迟 / 邻居扫描 / 信道统计）

**`speedtest`（32 KB）** —— 明显是从 **Ookla speedtest CLI** 改的：

```
c.speedtest.net
www.speedtest.net
speedtest-config.php
speedtest-servers-static.php?
speedtest-servers-custom
GET  /%s HTTP/1.0       ← 下载
POST /%s HTTP/1.0       ← 上传
Download speed: %0.2lf Mbps
Upload speed: %0.2lf Mbps
/tmp/speedtest_log
```

它还支持 “Local Speedtest Server” / “custom servers” 列表。

**`pingtest`（14 KB）** —— 自己发的 ICMP 探测：

```
Usage: pingtest [-c client] [-i interface] [-P packet size] [-R packet per second]
                [-j jitter time] [-t throughput test time] [-f flood] [-s WAN speedtest]
ICMP minimum/maximum/average latency
ICMP latency jitter
ICMP packet Sent/received
ICMP throughput pak/bytes success
/tmp/pingtestResult_%s
/tmp/speed_pingtestResult
```

**`broadband_ssl`（1.6 MB）** —— 实际入口是 HTTPS 建连和首批数据等待计时：

`main(hostname, mode)` 只在 mode 包含大写 `HTTPS` 时，对 `hostname:443` 发送
`GET / HTTP/1.0\r\n\r\n`，结果写 `/tmp/https_result` 和 `/tmp/ttfbs_result`。
第一段计时包括 TLS 建连和请求写入；第二段含 read 后一条 shell 日志的开销。
文件中保留的 ping / HTTP 下载 / speedtest 函数不能当作入口调用链。
逐函数还原、结果语义和证据见 [broadband_ssl](singtel-broadband-ssl.md)。

**`dhcp_scan`（203 KB）** —— libpcap 抓 DHCP，结果写
`/tmp/dhcp_<iface>_<mac>`，用来发现 LAN 上的客户端。

**`chanim_stats`（9 KB）** —— 读 Broadcom 的 chanim 表：
`chanspec / tx / inbss / obss / nocat / nopkt / doze / txop / glitch / knoise / idle / timestamp`。

> 也就是说：云端不仅能配置设备，还能**实测宽带速率、延迟抖动、邻居干扰**，
> 并把结果上报。这些测量是“真实执行”的，不是读现成计数器。

---

## 6. 自动重启策略（比想象中激进）

`rrm_bcm_arm` 里有一整套 `auto_reboot_*` 键，触发后直接 `/sbin/rebootWithReason`：

| 触发条件 | 键 |
|---|---|
| CPU 占用超阈值持续 N 分钟 | `auto_reboot_device_cpu_exceeded` / `auto_reboot_agent_cpu_exceeded` |
| 内存占用超阈值 | `auto_reboot_device_mem_exceeded` / `auto_reboot_agent_mem_exceeded` |
| DNS 连续失败 | `auto_reboot_dns_down` |
| Ping / HTTP(S) 连续失败 | `auto_reboot_ping_http_down` |
| 在线时长超限 | `auto_reboot_uptime_exceeded` |
| WAN 掉线 | `auto_reboot_wan_down` |
| 2.4G / 5G 射频掉线 | `auto_reboot_radio_24_down` / `_5_down` |

日志：

```
/data/reboot.log
/tmp/erm_config/reboot_log
/tmp/erm_config/reboot_logs
/tmp/erm_config/reboot_reasons
/tmp/erm_config/reboot_count
```

> **实际影响**：用户看到的“路由器自己重启了”，可能不是硬件问题，而是云代理
> 的策略触发。`cat /data/reboot.log` 能直接看到原因。

---

## 7. 固件升级链路

`image_manager` 的字符串：

```
Checking image
Checking image md5
Checking signature
Decrypting image
Decrypting image %s -> %s
Failed to decrypt the image
Invalid Embedur Signature
Invalid image signature
```

配合 `sig_key.pub`（RSA-2048）。流程是：**MD5 → 签名 → 解密 → 写入**。
签名公钥在代理包里，**私钥只在 EmbedUR 手里** —— 这一层设计是对的。

但注意：代理 tarball 本身（`/data/embedur/erm_agent.tar.bz2`）可以**由云端直接替换**，
`start_erm` 下一轮重启就执行新版本。这是典型的**远程供应链面**。

---

## 8. 它和 `mqtt_spy/` 的关系

之前的结论是：

> 命令格式没解出来；解码器在 extender 的**加密 rootfs** 里。

现在可以修正为：

- **Mesh Router 这份 rootfs 里就有解码器**（`rrm_bcm_arm`），没有加密；
- 之前尝试的 `?$[+` 分隔符、zlib、查表格式，都不是它的主要协议 ——
  它用的是 **标准 MQTT + JSON**；
- topic 与公共字段已经对上了（§4），本地 JSON 解析器的字段也挖出来了（§5.1），
  剩下的是**每个 method 的参数语义**。

也就是说：假 broker 的思路仍然有效，但要按 **JSON + 真实 topic** 来构造，
而不是继续猜分隔符。下一步最省事的做法是从 `rrm_bcm_arm` 里把
`json_handle_event` 一类函数反汇编出来。

---

## 9. ★ 安全问题（只描述，不贴材料）

### 9.1 固件里带着与生产证书**配对**的私钥

实测（模数比对）：

```
ca-prod.crt      modulus == mqtt-key-prod.pem      ← 同一对
ca-staging.crt   modulus == mqtt-key-staging.pem   ← 同一对
```

`ca-prod.crt` 的主体是：

```
C=SG, ST=Singapore, L=Singapore, O=Singapore Telecommunications Ltd,
OU=Connected Home, CN=*.wifi-analytics.singnet.com.sg
issuer: C=US, ST=California, L=Fremont, CN=embedUR systems
```

也就是说：**生产 broker 的证书私钥随固件一起发到了每一台设备**。
拿到固件的人可以导出这对材料；如果代理把它当作信任锚/客户端证书，
就能在链路上冒充云端（中间人）。

> **本仓库不收录任何私钥或证书内容** —— 只记录“存在且配对”这个事实。
> 这属于需要向厂商披露的问题（见 [NOTICE.md](../NOTICE.md) 的负责任披露）。

### 9.2 其他

| 问题 | 说明 |
|---|---|
| **默认开启** | `ARC_3rd_EmbedUR_Enable=1`，用户不看不知道 |
| **root 权限** | 代理以 root 运行，能改配置、重启、刷机 |
| **可远程换代** | `/data/embedur/erm_agent.tar.bz2` 被云端覆盖后即生效 |
| **测试环境可切** | 一个持久化文件就能把设备指到 `118.201.155.242` |
| **过期信任根** | `mqtt-cert.pem` 是 DST Root CA X3（2021-09-30 已过期） |
| **本地 1883** | 若包里带 mosquitto，会在 `0.0.0.0:1883` 起一个无认证 broker（本版本未带） |

---

## 10. 自己验证（命令）

```bash
R=/path/to/rootfs

# 1. 开关
grep ARC_3rd_EmbedUR_Enable $R/usr/share/config/etc/config/.glbcfg

# 2. 解包
cp $R/usr/bin/embedur/erm_agent.tar.bz2 /tmp && cd /tmp
tar xjf erm_agent.tar.bz2
cat erm_agent/erm_config erm_agent/version

# 3. topic
strings -n 6 erm_agent/rrm_bcm_arm | grep -E 'devices/|groups/|jioiot/|gateway_state'

# 4. 证书与私钥是否配对（只比模数，不输出私钥）
for c in ca-prod.crt ca-staging.crt; do
  openssl x509 -in erm_agent/$c -noout -modulus | openssl md5
done
for k in mqtt-key-prod.pem mqtt-key-staging.pem; do
  openssl rsa -in erm_agent/$k -noout -modulus | openssl md5
done

# 5. 看设备上代理是不是在跑
ps | grep -E 'rrm_bcm_arm|start_erm'
cat /data/reboot.log 2>/dev/null | tail
```

---

## 11. 还没解的

1. **命令 JSON schema**：外层 envelope（`id`/`type`/`statetype`/`category`/`timestamp`）
   和 `accesspoint`+`desired_state` 的分派已确认，`location` 的写入路径也确认；
   还差 **`desired_state` 其它字段**（`members`/`radio_24`/`radio_5`/`enh_steer_config`）
   和 **`direct` / `image` 的 payload** 具体落到哪些配置键。
2. **adornment 的完整结构**：只拿到片段（`ap/ssid/bssid/state/timer`）。
3. **`broadband_ssl`**：实际入口与应用函数已[逐函数分析](singtel-broadband-ssl.md)；
   仍缺云代理构造命令及外层 timeout / 清理策略的确切调用点。
4. **签名/加密固件包**：[image_manager 容器](singtel-embedur-image-format.md) 已有结构说明，
   实际 key 与调用方参数角色仍待证实。

这些都不影响“它在干什么”的判断，只影响“能不能自己伪造命令”。

---

## 12. 证据索引

| 内容 | 位置 |
|---|---|
| 启动开关 | `/usr/share/config/etc/config/.glbcfg` → `ARC_3rd_EmbedUR_Enable=1` |
| 启动脚本 | `/sbin/arc_embedur`、包内 `start_erm` |
| 环境配置 | `erm_agent/erm_config`、`erm_config_staging` |
| MQTT 主题 | `rrm_bcm_arm` 字符串：`devices/%s/adornment` 等 |
| 订阅注册函数 | `0x59A04`（拼主题）/ `0x59E68`（desired_state、direct）/ `0x771FC`（adornment）/ `0x70494`（image） |
| 本地 JSON 解析 | `handle_json_socket` @ `0x4E218`；`accesspoint`/`desired_state` 比较 @ `0x4E944`/`0x4E958` |
| 家长控制 | `member_filters_0x…` 链 + `-m string --dport 53`；配置 `/data/embedur/parental_controls.json` |
| 证书配对 | `ca-prod.crt` ↔ `mqtt-key-prod.pem`（模数一致） |
| 构建出处 | 二进制里的 Jenkins 路径 `SMR-2.3.29` |
| 多平台支持 | `systematic_reboot.sh` 的 `sagemcom / arcadyan / arcadyan_mtk / sercom_bcm / edgecore / jio_bcm` 分支 |
