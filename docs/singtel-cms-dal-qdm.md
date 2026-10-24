# Singtel 的 CMS DAL / QDM 函数地图（TR-098/181）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`libcms_dal.so`（302 个导出函数）、`libcms_qdm.so`（180 个）
> 作用：这两层是 Broadcom CMS 数据模型与真实网络配置之间的“翻译层”。

---

## 1. 分层

```
TR-069 / consoled / cfgview
        ↓
libcms_core   （MDM 数据模型、对象、配置 flash）
        ↓
libcms_dal    （数据访问：WAN/LAN/PMap/QoS/DNS/证书…）
        ↓
libcms_qdm    （查询/映射：full path ↔ ifname、VLAN、IPv6、路由…）
        ↓
实际网络配置（vlanctl / brctl / iptables / dhcpd …）
```

命名后缀：

```
_dev2  → Data Model Device 2（TR-181）
_igd   → InternetGatewayDevice（TR-098）
```

同一功能通常有两套实现。

---

## 2. `libcms_dal.so` 的 302 个函数

按前缀统计：

| 前缀 | 数量 | 作用 |
|---|---:|---|
| `dalWan` | 41 | WAN 连接/IP/PPP/DHCP |
| `dalLan` | 36 | LAN 接口/DHCP 服务器/主机 |
| `cmsDal` | 32 | 通用：认证、登录、syslog、版本、NAT 开关 |
| `dalPMap` | 19 | 端口映射 / 端口触发 |
| `dalSec` | 16 | 安全（防火墙/访问控制） |
| `dalQos` | 12 | QoS 队列/分类 |
| `dalEth` | 11 | 以太网接口 |
| `dalIp` | 10 | IP 接口 |
| `dalDns` | 9 | DNS |
| `dalRt` | 8 | 路由 |
| `dalCert` | 8 | 证书 |
| `dalVirtualServer` | 5 | 虚拟服务器（端口转发） |
| `dalRip` | 5 | RIP |
| `dalUrlFilter` | 4 | URL 过滤 |
| `dalStaticRoute` | 4 | 静态路由 |

### 值得注意的函数

```
cmsDal_authenticate                  ← CMS CLI/console 认证
cmsDal_getCurrentLoginCfg / setLoginCfg
cmsDal_getCurrentSyslogCfg / setSyslogCfg
cmsDal_getDefaultGatewayAndDnsCfg
cmsDal_getEnblNatForWeb_igd / _dev2
cmsDal_getEnblFullconeForWeb
cmsDal_getNetworkAccessMode_igd / _dev2
cmsDal_moveIntfLanWan
cmsDal_getWANProtocolFromIpConn / FromPppConn
dalCert_addCert / copyCert           ← 证书管理
dalPMap_*                            ← 端口映射
dalQos_*                             ← QoS
dalUrlFilter_*                       ← URL 关键字过滤
```

---

## 3. `libcms_qdm.so` 的 180 个函数

按前缀统计：

| 前缀 | 数量 | 作用 |
|---|---:|---|
| `qdmIpIntf` | 57 | IP 接口（IPv4/IPv6） |
| `qdmIntf` | 25 | 通用接口：full path ↔ ifname、上下层 |
| `qdmMulti` | 18 | 多播 |
| `qdmModsw` | 18 | 模块开关 |
| `qdmIpv6` | 9 | IPv6 |
| `qdmRt` | 8 | 路由 |
| `qdmQos` | 8 | QoS |
| `qdmVlan` | 7 | VLAN |
| `qdmEth` | 5 | 以太网 |
| `qdmTr69c` | 4 | TR-069 客户端 |
| `qdmDns` | 4 | DNS |
| `qdmWifi` | 3 | WiFi |

### 关键函数

```
qdmIntf_fullPathToIntfnameLocked_igd/_dev2
qdmIntf_intfnameToFullPathLocked_igd/_dev2
qdmIntf_getLowerLayersFromFullPathLocked
qdmIntf_getPathDescFromIntfnameLocked
qdmIntf_getStatusFromFullPathLocked
qdmEth_getEthernetVlanTermination
qdmDns_getActiveIpvxDnsIpLocked
qdmDhcpv4Client_getReqOption / getSentOption
qdmRt_* / qdmIpv6_* / qdmQos_*
```

即：**TR-098 的 `InternetGatewayDevice.*` 路径** 通过 `qdm*` 解析成
实际的 `eth0.10` / `br0` / `ppp0` 等接口名，再由 `dal*` 落到具体服务。

---

## 4. 与其它配置系统的关系

| 层 | 存储/入口 |
|---|---|
| TR-069 ACS | CWMP → `tr69` → CMS |
| CMS 数据模型 | `libcms_core` / `libcms_dal` / `libcms_qdm` |
| Arcadyan 配置 | `.glbcfg` → `mng_cli` → `midcore` |
| 实际网络 | `arc_*` 脚本 / `wl` / `vlanctl` / `iptables` |

CMS 操作最终会调用 Arcadyan 的服务（或写 `.glbcfg`），
所以同一个设置可能有两份来源，改错一边会被另一边覆盖。

---

## 5. 证据索引

| 内容 | 位置 |
|---|---|
| DAL 函数 | `libcms_dal.so`（302 个导出） |
| QDM 函数 | `libcms_qdm.so`（180 个导出） |
| 核心 | `libcms_core.so`（MDM/Obj/Mgm） |
| CLI | `libcms_cli.so` / `/bin/consoled` |
| 配置 flash | `cmsMgm_*`（CRC/压缩头） |
