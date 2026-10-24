# Singtel Mesh Router 的网络面：防火墙 / QoS / VLAN / WAN / Mesh / USB

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b，BCM963138）
> 材料：解包后的 UBIFS rootfs（`/sbin`、`/usr/share/config/etc/config/.glbcfg`）
> 方法：这些 `arc_*` 大多是 **ELF 二进制**，所以用 `strings` 取规则模板 + 配置默认值，
> 再和 `.glbcfg` 的字段逐条对上。**能直接看到完整 iptables/tc 命令行**。

---

## 0. 总览：谁在管网络

| 程序 | 类型 | 作用 |
|---|---|---|
| `arc_firewalld` | ELF | ★ IPv4 防火墙：生成 `/tmp/.ipt` 并 `iptables-restore` |
| `arc_firewall6` | ELF | ★ IPv6 防火墙：`ip6tables` 规则 |
| `arc_qos` | ELF | ★ 流量整形（hfsc / htb）+ 自动测速 |
| `arc_vlan` | shell | `bcm_vlanctl` 建 WAN VLAN 与假 `eth0.0` |
| `arc_wan` / `arc_if6` | ELF | WAN 拨号、策略路由、IPv6 SLAAC/PD/NAT64 |
| `arc_wbd` | ELF | Broadcom WBD：mesh 回传（`wbd_master` / `wbd_slave`） |
| `arc_switch` | shell | RDPA / `ethswctl` / xDSL 初始化 |
| `arc_storage` | ELF | USB 挂载/格式化、Samba/DLNA/FTP 的前置 |
| `arc_ltecmd` | ELF | LTE dongle 的 AT 命令（Huawei 风格） |
| `arc_modules` | shell | 加载内核模块（含厂商自定义 xt 模块） |
| `arc_netctrl` / `arc_net_param` | shell | conntrack 超时与上限 |
| `arc_pthrouth` | shell | PPPoE / IPv6 透传（`/proc/pthrough`） |
| `arc_hostinfo` | shell | 把主机名固定成 `localhost` |
| `arc_fwt` | shell | **telnetd 启动被注释掉**（只剩注释） |

---

## 1. ★ IPv4 防火墙（`arc_firewalld`）

### 1.1 工作方式

二进制里能看到完整的规则模板和调用：

```
iptables-restore /tmp/.ipt
-A LOG_DROP -j DROP
-A LOG_DROP -j ULOG --ulog-prefix "IPTABLES denied:"
```

即：每类规则（AC、DMZ、UPnP、端口映射、IPsec、L2TP…）在 C 里拼字符串，
写进 `/tmp/.ipt`，一次性 `iptables-restore`。日志走 `ULOG`，前缀固定。

### 1.2 主要链

```
INPUT / FORWARD / OUTPUT
  ├─ access_control        ← 按 LAN 客户端的访问控制（每天/时间段）
  ├─ url_blocking          ← 关键字过滤（自定义 xt_webstr）
  ├─ mac_filter            ← MAC 黑白名单
  ├─ SYN_FLOOD / UDP_FLOOD / SMURF_ATTACK / FRAGGLE_ATTACK / PING_TO_DEATH
  ├─ BLOCK_NETBIOS         ← 默认开：丢 UDP/137
  ├─ TR69_RULES            ← 只放行 TR-069 的端口
  ├─ F_REMOTE_MANAGEMENT   ← 远程管理（限定接口 + 源 IP 段）
  ├─ upnp_forward          ← UPnP 映射
  ├─ lan_devices_check     ← 只允许已知 LAN 设备的源 MAC
  ├─ trigger_out           ← 端口触发（ipt_TRIGGER）
  └─ src_mac_chain / ingress_if_chain / source_chain  ← QoS 打标
```

### 1.3 能看到的关键规则（原样）

```iptables
-A FORWARD -j LOG_DROP
-A INPUT  ! -i <lan_if> -j LOG_DROP
-A INPUT  -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
-A INPUT  -i lo -m conntrack --ctstate NEW -j ACCEPT
-A INPUT  -i <lan_if> -m conntrack --ctstate NEW -j ACCEPT

# DoS（仅当 ARC_FIREWALL_IDS_AntiDOS=1 才装）
-A INPUT  -i <if> -p tcp --syn -j SYN_FLOOD
-A INPUT  -i <if> -p udp -j UDP_FLOOD
-A FORWARD -i <if> -p icmp --icmp-type echo-request -m pkttype --pkt-type broadcast -j SMURF_ATTACK
-A FORWARD -i <if> -p udp --dport 19 -m pkttype --pkt-type broadcast -j FRAGGLE_ATTACK
-A INPUT  -i <if> -p icmp -m length --length 65535 -j PING_TO_DEATH
-A FORWARD -i <if> -j BLOCK_NETBIOS

# 防伪造
-A FORWARD ! -i <lan_if> -o ppp<idx> -j DROP
-A FORWARD -i <if> -m conntrack --ctstate NEW -p tcp --tcp-flags ACK ACK -j REJECT --reject-with tcp-reset

# MSS 钳制（PPPoE / 隧道）
-A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
-A FORWARD -p tcp --tcp-flags SYN,RST SYN -m tcpmss --mss <n>: -j TCPMSS --set-mss <n>

# 组播 / DHCP
-I INPUT -d 224.0.0.0/4 -i <if> -j ACCEPT
-I INPUT -i br0 -p udp --dport 68 -j DROP      ← 挡住 LAN 侧 DHCP 客户端报文
```

### 1.4 远程管理

```iptables
-A INPUT -d <wan_ip> -p tcp --dport <port> -j F_REMOTE_MANAGEMENT
-A F_REMOTE_MANAGEMENT -i <if> -m conntrack ! --ctstate INVALID -j ACCEPT
-A F_REMOTE_MANAGEMENT -i <if> -m iprange --src-range <a>-<b> -j ACCEPT
-A F_REMOTE_MANAGEMENT -j LOG_DROP
```

支持「只允许某个来源 IP 段」——对应 `ARC_UI_WEB_REMOTEMN_ExposeToIP`。

### 1.5 访问控制 / 网址过滤

```iptables
-A FORWARD -i <lan_if> -j access_control
-A access_control -m iprange --src-range <a>-<b> -j ac_rule_<n>
-A ac_rule_<n> -p tcp -m multiport --dports <ports> -j url_blocking
-A url_blocking -m webstr --host "<host>" -j LOG_DROP
-A url_blocking -m webstr --url "<url>" -j LOG_DROP
```

`webstr` 是**厂商自定义的 iptables 匹配模块**（`xt_webstr.ko`），
按 HTTP Host/URL 做关键字匹配 —— 不是标准 netfilter 功能。

### 1.6 出厂默认值（`.glbcfg`）

| 键 | 默认 | 含义 |
|---|---|---|
| `ARC_FIREWALL_Enable` | **1** | 防火墙开 |
| `ARC_FIREWALL_IDS_BlockNetbios` | **1** | 丢 137/udp |
| `ARC_FIREWALL_IDS_BlockWANPing` | **0** | **允许 WAN ping** |
| `ARC_FIREWALL_IDS_AntiDOS` | **0** | **抗 DoS 默认关** |
| `ARC_FIREWALL_DMZ_Enable` | 0 | DMZ 关 |
| `ARC_FIREWALL_MACFILTER_Enable` | 0 | MAC 过滤关 |
| `ARC_FIREWALL_AC_Enable` | 0 | 访问控制关 |
| `ARC_FIREWALL_URL_RULE_*` | 空 | 无关键字 |

### 1.7 NAT / 端口映射 / UPnP

```iptables
-A POSTROUTING -o <wan> -j MASQUERADE
-A POSTROUTING -o <wan> -j MASQUERADE --mode fullcone     ← 支持全锥形 NAT
-A PREROUTING -p tcp -d <wanip> --dport <a>:<b> -j DNAT --to-destination <ip>:<c>-<d>
-A FORWARD -p tcp -d <ip> --dport <port> -j ACCEPT
-A FORWARD -j upnp_forward
-A FORWARD -j trigger_out
-A trigger_out -i <lan> -p tcp --dport <port> --tcp-flags SYN SYN \
    -j TRIGGER --trigger-type out --trigger-proto <proto> --trigger-match <p> --trigger-relate <q>
```

`fullcone` 与 `TRIGGER` 也都是内核模块（`nf_nat` + `ipt_TRIGGER`）。

---

## 2. ★ IPv6 防火墙（`arc_firewall6`）

**默认丢**（规则末尾）：

```ip6tables
-A INPUT -i lo -j ACCEPT
-A INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
-I INPUT -i br+ -m conntrack --ctstate NEW -j ACCEPT
-A INPUT -m rt --rt-type 0 -j DROP                 ← 丢源路由
-A INPUT -i <wan> --dest ff00::/8 -j DROP          ← 丢 WAN 侧组播
-A INPUT -p tcp --dport 80 -i <wan> -j DROP        ← WAN 侧禁止 HTTP
-A INPUT -p tcp --syn --dport 80 -i <lan> -j ACCEPT
-A INPUT -p udp --dport 546:547 -j ACCEPT          ← DHCPv6
-A INPUT -p udp --dport 53  -i <lan> --match limit --limit 100/sec -j ACCEPT
-A INPUT -p udp --dport 123 -i <lan> --match limit --limit 10/sec  -j ACCEPT
-A INPUT --match limit --limit 100/sec -j REJECT --reject-with icmp6-adm-prohibited
-A INPUT -j DROP
```

放行的 ICMPv6（都带限速）：`no-route`、`packet-too-big`、`time-exceeded`、
`unknown-header-type`、`unknown-option`、`echo-request/reply`(300/s)、
`neighbour-solicitation/advertisement`(100/s)、`router-advertisement`(10/s)、
`router-solicitation`、MLD 130/131/132/143、151/152/153。

转发侧：

```ip6tables
-A FORWARD -m rt --rt-type 0 -j DROP
-A FORWARD --source fe80::0/64 -j DROP
-A FORWARD --dest   fe80::0/64 -j DROP
-A FORWARD -s fc00::/7 -j REJECT
-A FORWARD -d fc00::/7 -j REJECT
```

即：**不做 IPv6 NAT、不转发链路本地与 ULA**，只允许公网前缀。

---

## 3. ★ QoS（`arc_qos`）

两种队列：

- 默认 **HFSC**（`tc qdisc add dev %s root handle 2: hfsc default %x`）
- 也支持 **HTB**（`tc qdisc ... root handle 2: htb default %x`）

每条 tc 命令都能看到：

```sh
tc qdisc add dev <wan> root handle 2: hfsc default 0x<id>
tc class add dev <wan> parent 2:  classid 2:1 hfsc sc m2 <rate>mbit
tc class add dev <wan> parent 2:1 classid 2:<id> hfsc sc m2 <kbit> ul rate <kbit>
tc class add dev <wan> parent 2:<id> classid 2:<id2> hfsc rt m1 <kbit> d <ms> m2 <kbit> ls m2 <kbit> ul rate <kbit>
tc filter add dev <wan> parent 2: prio 1 protocol ip handle <mark> fw flowid 2:<id>
tc qdisc add dev <wan> parent 2:<id> handle <h>: sfq quantum <n> perturb 10
tc qdisc add dev <wan> parent 2:<id> handle <h>: prio bands <n>
```

**自动测速**：`qos_get_wan_rate_1/2` 用 ICMP ping 网关 / DNS 来估链路速率，
字符串里直接写着：

```
BandWidth form Ping gateway mode wan_qos_rate =[%u]
BandWidth form Ping DNS mode wan_qos_rate =[%u]
download_rate=%d, upload_rate=%d, link_layer=%s, overhead=%d, is_ipsec=%d
```

`overhead` 与 `linklay` 会进 HTB 参数（PPPoE/ATM 开销补偿）。
分类依据是 **MAC / 入接口 / connmark**：

```iptables
-A src_mac_chain -m mac --mac-source <mac> -j MARK --set-mark 0x<mark>/0x<mask>
-A ingress_if_chain -i <if> -j MARK --set-mark ...
-A source_chain -m mac --mac-source <mac> -j CONNMARK --set-mark ...
-A FORWARD -j CONNMARK --restore-mark
```

出厂默认：`ARC_QOS_Enable=1`、`WMM=1`、`NOACK=0`、`AutoRateMode=0`、
`ARC_QOS_UploadRate=900000000`（900 Mbps 占位）。

---

## 4. WAN / VLAN

`arc_wantype` 把 `ARC_WAN_BaseType` 映射成物理口：

| 类型 | 值 | 接口 |
|---|---:|---|
| ADSL | 0 | `nas0` / `nas1` |
| Ethernet | 1 | `eth0` |
| VDSL | 2 | `ptm0` |
| G.Fast | 3 | `ptm0` |
| LTE | 4 | `eth6` |

`arc_vlan` 用 `bcm_vlanctl` 建 VLAN：

```sh
bcm_vlanctl --if-create <base> <vid> ...
bcm_vlanctl --push-tag --set-vid <vid> 0 --set-pbits <pcp> 0 ...
bcm_vlanctl --set-rxif <if> --filter-vid <vid> --pop-tag ...
```

★ 还会建一个**假 VLAN `eth0.0`**，专门用来「自动探测 DHCP 服务器」——
这就是 Singtel 光猫/ONT 侧 VLAN 自动识别（`ARC_WAN_VLAN_Detecting=1`）的实现。

`arc_wan` 做策略路由：

```sh
ip route add default via <gw> dev <if> table rt_wan<idx>
ip rule add from <src> lookup rt_wan<idx> prio 1000
```

每个 WAN 一条路由表（`rt_wan0`、`rt_wan1`…），源地址选路。

---

## 5. Mesh / WBD（`arc_wbd`）

Broadcom 的 **WBD**（Wireless Backhaul Daemon）：

```
wbd_master &        ← 主节点
wbd_slave &         ← 从节点
killall -9 wbd_master / wbd_slave
```

nvram 参数（`nvram_set_brcm` 写入，`libarc-nvramsync.so` 同步）：

```
bh_ssid / fh_ssid          ← 回传 / 前传 SSID
bh_wpa_psk / fh_wpa_psk    ← 对应 PSK
bh_akm / bh_crypto         ← AKM / 加密方式
bh_map / fh bh / bh_band   ← 频段与映射
multiap_mode / multiap_almac / multiap_ctl_almac
wbd_mode / wbd_fbt / wbd_bh_opt / wbd_auto_config / wbd_fixed_ifnames
wbd_tbss_thld_2g / _5g / wbd_tbss_algo
```

`ARC_WBD_Mode=0`、`ARC_WBD_BHband=5G` 是出厂默认。
`arc_ieee1905_owl` 再加载 `arc_oshal.ko` + `drv_atdp.ko`，用
`arc_atdp_util init <bh_ssid> <al_mac> 1 128 128 4 3` 启动 ATDP，
并把 `eth1–eth4`、`wl0.2`、`wl1.2` 都加入转发。

---

## 6. IPv6 接入

`arc_if6` 支持：

| 方式 | 关键字段 |
|---|---|
| SLAAC / RA | `start_ipv6_slaac`、`accept_ra`、`/usr/sbin/ip -6 route` |
| DHCPv6-PD | `ARC_IP6_DelegatePrefix` / `...PrefixLen` |
| 6RD | `ARC_IP6_6RD_*`（默认 `2400:D803::/32`，border relay `6rd.singnet.com.sg`） |
| 6to4 | `ARC_IP6_6TO4_*`（默认 relay `192.88.99.1`） |
| NAT64 | `ARC_IP6_EnableNAT64`、`ARC_IP6_NAT64_Prefix`（默认 `/96`） |
| NAT46 | `ARC_IP6_EnableNAT46`、`ARC_IP6_NAT46_Addr`（默认 `10.0.0.0/8`） |

前缀模式在字符串里能直接看到运营商名字：

```
prefix_orig / prefix_mode_1
singtel_prefix / singtel_addr
gn_prefix      / gn_addr
bytel_prefix   / bytel_addr
nat64_prefix
```

即固件同时为 **Singtel / GN / Byte（MyRepublic?）** 预留了前缀模板。

默认：`ARC_IP6_AutoEnable=1`、`EnableFirewall=1`、`TunnelType=2`（6RD）。

---

## 7. USB 存储

`arc_storage` 的字符串：

```
mount [%s] as ntfs   → ntfs-3g %s %s
mount [%s] as ext3   → chown -R root:root %s ; chmod a+rwx -R %s
mount [%s] as ext2
mkfs.ntfs -Q /dev/%s
mkfs.ext2 /dev/%s1
e2fsck /dev/%s
/sbin/fdisk /dev/%s < %s
```

★ 挂载 ext2/3 后直接 **`chmod a+rwx -R`** —— 任何本地用户都能读写整个盘。
配合 Samba 的 `guest_account root`（见
[config-recovery.md](config-recovery.md)），USB 盘默认是完全敞开的。

---

## 8. LTE dongle

`arc_ltecmd` 只认 **Huawei 风格**的 AT 命令：

```
AT^SYSINFOEX          ← 模块状态/制式
AT+CIMI               ← IMSI
AT^CPIN?              ← SIM PIN 状态
AT+CPIN="<pin>"       ← 解锁
AT+CPIN="<pin>","<puk>"
AT+CLCK="SC",0|1|2,"<pin>"   ← 开关/查询 SIM 锁
AT+CGDCONT=1,"IPV4V6","<apn>",,0,0
```

设备节点 `/dev/ttyUSB0`（或配置里的 `/dev/%s`），命令写到 `/tmp/AT.com`，
结果读 `/tmp/AT.out`。

---

## 9. 内核模块（`arc_modules`）

除了标准 netfilter，还专门加载了**厂商自定义模块**：

```
xt_webstr.ko      ← 网址关键字匹配（见 §1.5）
xt_SKIPLOG.ko     ← 跳过日志
ipt_TRIGGER.ko    ← 端口触发
xt_CLASSIFY.ko / xt_DSCP.ko / xt_dscp.ko
ipt_ULOG.ko
otp.ko            ← "presecure / fullsecure" OTP
bcm_pka           ← Packet Accelerator（echo 1 > /sys/devices/platform/bcm_pka/enable）
bcm_ingqos.ko
huawei_cdc_ncm.ko ← LTE dongle
dhd.ko / wl.ko    ← Broadcom WiFi（firmware_path=/usr/wlan/dhd）
```

★ 启动时还会把 `ARC_WLAN_MAC` 写进 `/etc/config/nvram.txt`：

```sh
sed -i "s/macaddr=.*/macaddr=$WLAN_MAC/g" /etc/config/nvram.txt
```

---

## 10. 其它系统面

`arc_netctrl`（conntrack 调优）：

```
nf_conntrack_max = 12288
tcp_timeout_established = 600
udp_timeout = 65
tcp_timeout_close = 10
tcp_timeout_fin_wait = 120
tcp_timeout_syn_sent = 120
icmp_timeout = 30
```

`arc_syslog`：日志压缩存到 `/data/syslogs_<日期>/`，`/data` 用量超 50% 时
删掉最旧的 1/3。

`arc_hostinfo`：把主机名固定成 `localhost`（避免向上游泄漏设备名）。

`arc_fwt`：**只剩一段被注释掉的 telnetd 启动**：

```sh
# Enable telnetd
#if [ -f /usr/sbin/telnetd ]; then
#	telnetd -l /bin/sh
#fi
```

真正的 telnet 开关在 `ARC_TELNETD_ENABLE`（另见主配置文档）。

---

## 10.1 CTF（Cut-Through Forwarding）加速

Broadcom 的 CTF 让已建立的流绕过部分 netfilter 路径，用户态通过
`/proc/net/ctf_ipc_option` 控制：

```
FilterAdd
SetWanIP <ip>
DelByIp <ip> / <ip_start> <ip_end>
DelByMac <mac>
DelByPort <proto> <port_start> <port_end>
```

对应 `libarc-shared.so` 的函数：

```
ctf_add_filter
ctf_set_wanip
ctf_ipc_del_by_ip_range
ctf_ipc_del_by_mac
ctf_ipc_del_by_port_range
clear_ctf_entries
```

相关文件：

```
/proc/net/ctf_ipc_option     命令入口
/proc/net/arp                ARP 表
/proc/net/route              路由表
/proc/net/if_inet6           IPv6 地址
/proc/sys/net/ipv6/conf/<if>/<param>
```

★ 安全点：CTF 表是**用户态可写**的（`/proc/net/ctf_ipc_option`，root 权限）。
删错/加错 filter 可能让流量**绕过防火墙/访问控制**，或者让已建立的流
继续走旧路径（策略更新不生效）。

---

## 11. 安全观察

1. **抗 DoS 默认关**（`ARC_FIREWALL_IDS_AntiDOS=0`），WAN ping 默认放行。
2. **USB 盘 `chmod a+rwx`**，Samba 又是 `guest_account root`。
3. **IPv6 防火墙默认丢**，这点做得比 IPv4 好；但允许 WAN 侧 ICMPv6 echo（限速 300/s）。
4. **`xt_webstr` 只匹配明文 HTTP**，HTTPS 的 SNI 不拦（主机名过滤可被绕过）。
5. **MAC 过滤**只在 `INPUT/FORWARD` 上按源 MAC 丢，伪造 MAC 即可绕过。
6. **`arc_wan` 的 `ppp<idx>` 反伪造规则**只对 PPP 接口生效。
7. `fullcone` NAT 打开后，内网端口对外可达性会提高（默认映射仍需显式配置）。

---

## 12. 证据速查

| 内容 | 位置 |
|---|---|
| iptables 规则 | `arc_firewalld` 字符串（`-A ...`） |
| ip6tables 规则 | `arc_firewall6` 字符串 |
| tc 命令 | `arc_qos` 字符串（`tc qdisc/class/filter`） |
| VLAN | `arc_vlan` shell 脚本 |
| WAN 类型映射 | `arc_wantype` shell 脚本 |
| WBD nvram 键 | `arc_wbd` 字符串 |
| IPv6 前缀模板 | `arc_if6` 字符串 |
| 出厂默认 | `usr/share/config/etc/config/.glbcfg` |
| 自定义内核模块 | `arc_modules` + `.glbcfg` 的 `ARC_*` 字段 |
