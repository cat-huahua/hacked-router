# Singtel Mesh Router 剩余服务脚本逐条解码

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/sbin/arc_*` 里之前没单独写过的脚本
> 目的：把“整机还有什么服务、它们怎么被拉起、读哪些配置键”补齐。

---

## 1. DHCP / DNS

### `arc_dnsmasq`

```sh
lan_ifname=`mng_cli get ARC_LAN_0_Ifname`
dnsmasq -i $lan_ifname -c 0
```

- 只监听 LAN 接口；
- **`-c 0` = DNS 缓存关闭**（每次都向上游查）。

### `arc_dhcpd_listener`

- 只在 **bridge 模式**（`ARC_WAN_0_BridgeEnable=1`）启动；
- 抓 DHCP，写两个文件：

```
/tmp/dhcpd_client_info.txt    客户端
/data/dhcpd_stb_info.txt      STB（IPTV 机顶盒）
```

- 这就是 `arc_correct_data` 去重的那份 STB 文件。

### `arc_dhcpc_cleaner`

WAN 网线拔掉（`ARC_WAN_PhyLink=0`）时，删除从该 WAN 学到的 DNS 主机路由：

```sh
route del -net <dns> netmask 255.255.255.255 gateway <gw> dev <if>
```

防止 4G dongle 和有线 WAN 的 DNS 路由打架。

---

## 2. 桥接与 AP 模式

### `arc_bridge`

把 LAN 口和所有 WiFi VAP 加进 `br0`：

```
eth1..eth4
wl1 / wl1.1 / wl1.2 / wl1.3      (2.4G)
wl0 / wl0.1 / wl0.2 / wl0.3      (5G)
wan0（仅 bridge 模式）
```

★ **发现一个脚本 bug**：2.4G 的 SSID1/2 分支里写的是

```sh
if [ -n $wl_24g1_iface ] ; then
    brctl addif $br_iface $wl_24g3_iface   # ← 应该是 $wl_24g1_iface
fi
if [ -n $wl_24g2_iface ] ; then
    brctl addif $br_iface $wl_24g3_iface   # ← 应该是 $wl_24g2_iface
fi
```

也就是 `wl1.1` / `wl1.2` 可能没有被正确桥接（或者被重复加 `wl1.3`）。
这会影响 2.4G 多 SSID（Guest/backhaul）的桥接行为。

### `arc_ap_mode`

在 AP 模式与路由模式之间切换：

| 模式 | WAN0 | WAN1 |
|---|---|---|
| AP（bridge） | `IP4_Proto=bridge`、IGMP/Mcast=1 | `bridge`、IGMP/Mcast=0 |
| 路由 | `IP4_Proto=dhcp` | `dhcp`、IGMP/Mcast=1 |

切换后 `mng_cli commit`；重启路径会 `mng_cli action reboot`。

---

## 3. WAN 接口与 MAC

### `arc_waniface`

- WAN MAC 的取法：

```
WAN base = LAN MAC + 4
```

  用 `macadd $lan_mac 4` 算出来，写回 `ARC_WAN_0_MACaddr` / `ARC_WAN_1_MACaddr`。
- 按 `ARC_WAN_x_IP6_Proto` 打开/关闭每个 WAN 的 IPv6
  （`/proc/sys/net/ipv6/conf/<if>/disable_ipv6`）。
- bridge 模式下强制打开 WAN 的 IPv6。

### `arc_wanup` / `arc_wandown`

链路 up/down 时，对 `ARC_WAN_Active` 里的每个索引发：

```
mng_cli action wan_start="wan_idx=0 wan_idx=1 ..."
mng_cli action wan_stop="..."
```

### `arc_dialing_rule`

```
/usr/sbin/sip_config SIP_CORE_DialRule_CFGSync
```

把拨号规则同步给 BrnSIP（VOIP 栈）。

---

## 4. WLAN（`arc_wlan`）

这是 2.4G 的主配置脚本，全部通过 `iwconfig` / `iwpriv` 操作 `wlan0` 和 VAP：

### 4.1 启动

```sh
iwpriv wlan0 sAddVap 1    # 创建 wlan0.1
iwpriv wlan0 sAddVap 2
iwpriv wlan0 sAddVap 3
iwconfig wlan0 essid Lantiq
set_wl_bssid 0..3
iwpriv wlan0 sCountry US        # ★ 注意：先设 US
ifconfig wlan0 up; ifconfig wlan0 down   # “dirty” 初始化
```

### 4.2 BSSID

```
BSSID = LAN MAC + (SSID 序号 + 9)
SSID0 的 BSSID 会写回 ARC_WLAN_MAC
```

### 4.3 无线模式

`ARC_WLAN_24G_RadioMode` → `sNetworkMode`：

| 模式 | 值 |
|---|---:|
| b | 17 |
| g | 18 |
| bg | 19 |
| n | 20 |
| gn | 22 |
| bgn | 23 |

### 4.4 信道 / 带宽

```sh
iwconfig wlan0 channel <n|auto>
iwpriv wlan0 sAocsBonding 1|0          # 下/上边带
iwpriv wlan0 sFortyMHzOpMode 0|1
iwpriv wlan0 sCoexMode 0|1
```

### 4.5 安全

- WEP：`iwconfig wlan0 key <hex> [id]` / `key s:<ascii> [id]`；
- WPA/WPA2：由 `hostapd` 负责（脚本只把接口 up）；
- MAC 过滤：`sAclMode 0/1/2`（关/允许/拒绝）、`sACL`、`sDelACL`。

### 4.6 WPS

```sh
hostapd_cli -i wlan0 wps_pin any <pin> 120
hostapd_cli -i wlan0 wps_pbc
```

### 4.7 其他

- `sIpxPpaEnabled 1` + `ppacmd addlan`：把 VAP 加进 Broadcom PPA 加速；
- `wps_workaround_for_win7`：Windows 7 下把 `WPS_Unconfigured` 置 0；
- `wl_assoclist`：从 `iwpriv wlan0 gConInfo` 抓关联客户端。

★ **硬编码 `sCountry US`**：启动时先设美国，之后才由驱动/配置覆盖；
`ARC_WLAN_24G_CountryCode=SG` 是否真的生效，取决于后续 `iwpriv` 调用。

---

## 5. L2TP / IPsec 钩子

### L2TP（`arc_l2tpd_*`）

pppd 的 up/down 钩子，把状态写进临时配置：

```
L2TPD_STATUS_IFNAME_<if>
L2TPD_STATUS_PEERIP_<if>
L2TPD_STATUS_SPEED_<if>
L2TPD_STATUS_PEERNAME_<if>
```

并触发 `mng_cli action ui_vpn=l2tpd_mod`。

### IPsec（`arc_ipsec_user`）

strongSwan 的 `_updown` 脚本：

- 读取 `PLUTO_*` 环境变量；
- 按 `ARC_IPSEC_<n>_ConnName` 找到连接索引；
- 把 `PLUTO_VERB`、`PLUTO_INTERFACE`、`PLUTO_MY_CLIENT`、端口等写进
  `PLUTO_*_<idx>` 临时键；
- 触发 `ui_vpn=ipsecvpn_mod`（IPv4）或 `ui_ipv6_vpn`（IPv6）。

---

## 6. VOIP / SIP

这些脚本只是 `sip_config` 的薄封装：

| 脚本 | 调用 |
|---|---|
| `arc_phone_config` | `sip_config SIP_CORE_Phone_CFGSync 0` |
| `arc_sip_phone` | 同上 |
| `arc_sip_account` | `sip_config SIP_CORE_Multi_Account_Reset 20 1 0 ...` |
| `arc_speed_dial` | `sip_config SIP_CORE_Speed_Dialing_CFGSync` |
| `arc_dialing_rule` | `sip_config SIP_CORE_DialRule_CFGSync` |
| `arc_siplog_callin_clear` | `sip_config TEL_LOG_Del_CallIN_Record` |
| `arc_siplog_callout_clear` | `sip_config TEL_LOG_Del_CallOUT_Record` |
| `arc_sip_alg` | 按 `ARC_SYS_SIPALG_Enable` 加载 `nf_conntrack_sip`/`nf_nat_sip`，并清 5060 的 conntrack |

`/usr/sbin/sip_config` 是 BrnSIP 的配置客户端。

> ★ **实测：这个二进制在 rootfs 里不存在**（`find` 全盘只找到调用它的脚本，
> 没有 `sip_config` / `sipd` / `brnsip`）。也就是说 **VOIP/SIP 这一整套脚本
> 在这个固件里是“死代码”** —— 没有电话端口/语音功能的机型不会运行它们。
> 参数语义因此不再深挖（见 §11）。

---

## 7. IPTV / ALG

### `arc_alg_modules`

按 `ARC_ALG_*_Enable` 动态加载/卸载：

```
nf_conntrack_ftp / nf_nat_ftp
nf_conntrack_tftp / nf_nat_tftp
nf_conntrack_rtsp / nf_nat_rtsp
nf_conntrack_sip / nf_nat_sip
nf_conntrack_h323 / nf_nat_h323
```

### `arc_iptvled`

只是启动/停止 `arc_iptvled_daemon`（IPTV 灯效）。

---

## 8. 时区与 DNS

### `arc_update_tz`

把 `ARC_SYS_TimeZone` 映射到 `/usr/share/zoneinfo` 里的文件，
建 `/etc/localtime` 符号链接。带一张老 TZ 值到新值的修正表：

```
FET-3 → EET-2EEST,M3.5.0/3,M10.5.0/4
MSK-4 → MSK-3
EST-10 → AEST-10
...
```

### `arc_update_st_dns`

Singtel 专用 `resolv.conf` 生成：

- **路由模式**：`ARC_WAN_0_IP4_DNS` + `127.0.0.1`
- **AP/bridge 模式**：先 `nslookup dnscache1/2.singnet.com.sg`，
  取 Singtel DNS 的 IP，再加 `127.0.0.1`

---

## 9. 恢复出厂

### `arc_mt_reset`

```sh
arc_glbcfg start
mngcli set ARC_WAN_100_Iface=eth0.10
mngcli set ARC_WAN_101_Iface=eth0.20
mngcli set ARC_WAN_100_MACaddr=`mngcli get ARC_WLAN_MAC`
mngcli set ARC_WLAN_BAND=5
mngcli set ARC_SYS_IsFactoryDefault=1
mngcli commit
mngcli action ui_clear_log
rm -rf /data/dhcpd.leases*
```

即：**重跑板级数据 → 修正 WAN VLAN → 标记出厂 → 提交 → 清日志/租约**。

---

## 10. 其他系统脚本

| 脚本 | 作用 |
|---|---|
| `arc_commit` | `mng_cli commit` |
| `arc_reboot` | 写 `/proc/sys/blink_diag_led`，`kill 1` |
| `arc_make_link` | 预留（内容被注释） |
| `arc_correct_data` | 去重 `/data/dhcpd_stb_info.txt` |
| `arc_deviceready` | 设 pinmux、关红电源灯、`arc_led power on` |
| `arc_loopback` | 拉起 `lo`，清空 `udhcpd.leases` |
| `arc_mount` | `mount -a`、建 `/var` 目录、复制 `smb.conf` |
| `arc_mdevs` | 跑 `makeDevs.sh` 创建设备节点 |
| `arc_nvram` | 空实现 |
| `arc_swmdk` | 起 `/bin/swmdk` |
| `arc_printk` | 设 printk 级别；**生成 `/usr/bin/mngcli_search`** |
| `arc_visualization` | 起 `vis-dcon` / `vis-datacollector`（数据采集） |
| `arc_qtn_init` | Quantenna WiFi 初始化（tftpd 192.168.2.1:69、qcsapi） |
| `arc_lte` | Huawei 12d1:15cd modeswitch + `pppd call wcdma` |
| `arc_pc_list` | 起 `pc_list_daemon` |
| `arc_async_event` | 起 `async_event` |
| `arc_ntpclient` | 起/停 `arc_ntpdaemon` |
| `arc_routes6` | 清 IPv6 路由表 200 |

### `swmdk`：Broadcom Switch MDK

`/bin/swmdk`（由 `arc_swmdk` 启动）是 Broadcom **Switch MDK / BMD**，
面向 **BCM6300 / BCM63100** 交换芯片，负责：

```
PHY 配置 / link status
VLAN（BMD_CONFIG_DEFAULT_VLAN、port default vlan）
QoS（DSCP→priority、WRR、rate control、egress queue）
port STP / port mode / port MAC
DMA / IMP / Higig
```

字符串里能看到 `bcm6300_a0_bmd_*` / `bcm63100_a0_bmd_*` 和 `binding socket`，
即它通过 socket 接受命令、直接操作交换芯片寄存器。

### Quantenna（`qcsapi`）：本机型不存在

`arc_qtn_init` 引用了：

```
call_qcsapi_sockrpc
arc_cfg_qcsapi_app
/usr/sbin/Quantenna/
```

但全盘 `find` **没有** `qcsapi` / `Quantenna` / `call_qcsapi_sockrpc`。
⇒ **`arc_qtn_init` 在这个机型上是死代码**（给带 Quantenna 5G 模块的别的型号用的）。

### ★ `owl-tplg`：OWL 拓扑的真实接口

```sh
wget http://127.0.0.1:55761/status/tplg -O /tmp/dev-info
```

返回 JSON，字段：

```
device_name / device_id / parent_id / connect_type
```

脚本把它解析成 `/tmp/dev-name`、`/tmp/dev-id`、`/tmp/dev-parent`、
`/tmp/dev-type`，再拼成树。

**这是 OWL/SON 拓扑的本地 HTTP 接口（端口 55761）**，比之前的
dbus/1905 描述更直接 —— 想读 mesh 拓扑，直接 GET 这个地址即可（在设备上）。

---

## 11. 还没逐条解的部分（如实记录）

| 区域 | 状态 |
|---|---|
| `sip_config` 的参数语义 / BrnSIP 协议 | 只知道调用点，没解参数 |
| `libArcOWLcore.so` / `libArcOWLapi.so` 的消息层 | 只确认分层与端口 55761 |
| `image_manager` 的加密容器格式 | 只确认 MD5+签名+解密 |
| `broadband_ssl` 的逐函数协议 | 只确认 HTTP 下载/上传线程 |
| `wps_monitor` 内部状态机 | 只确认 Broadcom WSC 结构 |
| `httpd` 的 `cli_tbl` 全表 | 只解了字段映射（webmap） |
| `libcms_core/dal/qdm` | 未解 |
| `pc_list_daemon` / `vis-*` / `async_event` 的内部 | 未解 |
| `swmdk` / `qcsapi`（Quantenna） | ✅ 已确认：`swmdk` = BCM6300/63100 交换芯片 MDK；`qcsapi` 本机型不存在（死代码） |

---

## 12. 观察与风险

1. **`arc_bridge` 的 2.4G SSID1/2 桥接 bug**（§2）—— 可能导致多 SSID 桥接异常。
2. **`sCountry US` 硬编码**（§4.1）—— 与 `CountryCode=SG` 可能冲突。
3. **`dnsmasq -c 0`** —— 不做 DNS 缓存，每次都上游查询。
4. **`arc_printk` 生成 `mngcli_search`** —— 一个便利的“全配置搜索”工具，
   也说明 `/usr/bin` 可写（rootfs 只读时实际写到 tmpfs）。
5. **`owl-tplg` 的 55761 端口** —— 只监听 127.0.0.1，但如果在设备上能执行命令，
   就能直接读拓扑。
6. **`arc_visualization` 的数据采集** —— `vis-dcon` / `vis-datacollector` 会上报
   什么，还没解。

---

## 13. 证据索引

| 内容 | 位置 |
|---|---|
| DHCP/DNS | `/sbin/arc_dnsmasq`、`arc_dhcpd_listener`、`arc_dhcpc_cleaner` |
| 桥接/AP | `/sbin/arc_bridge`、`arc_ap_mode` |
| WAN/WLAN | `/sbin/arc_waniface`、`arc_wlan` |
| L2TP/IPsec | `/sbin/arc_l2tpd_*`、`arc_ipsec_user` |
| VOIP | `/sbin/arc_sip_*`、`/usr/sbin/sip_config` |
| IPTV/ALG | `/sbin/arc_alg_modules`、`arc_iptvled` |
| 时区/DNS | `/sbin/arc_update_tz`、`arc_update_st_dns` |
| 恢复出厂 | `/sbin/arc_mt_reset` |
| OWL 拓扑 | `/sbin/owl-tplg`（`127.0.0.1:55761/status/tplg`） |
