# Singtel Mesh Router 的启动流程与事件总线

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：rootfs 的 `/sbin/sysup`、`/usr/share/msg/`、`/usr/agents/`、`/etc/pslist.conf`
> 结论：**这台设备的“服务编排”是一套 dbus + 文本动作脚本**，
> 启动顺序和运行时事件全都写在 `/usr/share/msg/` 里（210 个文件）。

---

## 1. 启动链（从上电到业务就绪）

```
CFE / u-boot
  ↓
kernel → /sbin/init
  ↓ /etc/inittab（preinit 生成）
::sysinit:/sbin/sysup
::shutdown:/sbin/sysdown
ttyS0::askfirst:/bin/login        ← 串口控制台
  ↓
/sbin/sysup（ELF，不是脚本）
  1. 处理 /etc/fstab、挂 /tmp/media
  2. cp -af /usr/share/config/etc/* /etc
  3. ln -sf /data/passwd /etc/passwd
  4. arccfg checkout                 ← 从 pricfg 分区解出用户配置
  5. /usr/sbin/servicemanager &
  6. dbus-uuidgen / dbus-daemon --system
  7. /usr/sbin/midcore &
     /usr/sbin/mng &
     /usr/sbin/arca-agent-loader /usr/agents &
  8. /usr/sbin/sysmonitor &
  9. arc_nvram_sync / arc_fw_md5sum
 10. arc_ledd
 11. mng_cli action sys_boot        ← ★ 逐条执行启动动作
```

`sysup` 里还能看到这几个“就绪标记”：

```
/tmp/.arca-midcore.ok
/tmp/.arca-agent-loader.ok
/tmp/.arca-mng-core.ok
/tmp/.arca-misc-agent.ok
/tmp/arc-middle
```

---

## 2. ★ `sys_boot`：完整的启动动作表

`/usr/share/msg/sys_boot` 是一个文本文件，每行一条：

```
<dbus 服务>:<动作> [参数]
```

按顺序执行（`#` 开头是注释/禁用）：

| # | 动作 | 作用 |
|---:|---|---|
| 1 | `arca.dbus.misc:sysctrl CMD_BOOT` | 内核参数、watchdog、内存水位 |
| 2 | `update_tz` | 时区 |
| 3 | `mdevs CMD_BOOT` | mdev 设备节点 |
| 4 | `mount CMD_BOOT` | 挂载 |
| 5 | `glbcfg CMD_BOOT` | 迁移/补齐配置字段 |
| 6 | `correct_data CMD_BOOT` | 修正坏配置 |
| 7 | `loopback CMD_BOOT` | lo |
| 8 | `dpi CMD_START` | 加载 `tdts.ko` / `dpicore.ko` |
| 9 | `modules CMD_BOOT` | 加载全部内核模块 |
| 10 | `alg_modules CMD_BOOT` | NAT ALG |
| 11 | `netctrl CMD_BOOT` | conntrack 调优 |
| 12 | `tunnel CMD_BOOT` | GRE |
| 13 | `swmdk CMD_BOOT` | 交换机 SDK |
| 14 | `switch CMD_BOOT` | RDPA / `ethswctl` |
| 15 | `vlan CMD_BOOT` | WAN VLAN |
| — | `#wanmode CMD_BOOT` | （注释） |
| 16 | `bridge CMD_BOOT` | br0 |
| 17 | `lan CMD_BOOT` | LAN 接口 |
| 18 | `lanmon CMD_BOOT` | LAN 监视 |
| 19 | `waniface CMD_BOOT` | WAN 接口 |
| 20 | `gpiod CMD_BOOT` | GPIO |
| 21 | `telnetd CMD_BOOT` | **默认关**（`ARC_TELNETD_ENABLE=0`） |
| 22 | `sshd CMD_START` | **默认关**（`ARC_SSHD_Enabled=0`） |
| — | `#async_event CMD_BOOT` | （注释） |
| 23 | `make_link CMD_BOOT` | 链路 |
| 24 | `syslog_ng CMD_BOOT` | syslog-ng |
| 25 | `tr69 CMD_BOOT` | TR-069 |
| 26 | `udevd CMD_BOOT` | udev |
| 27 | `console CMD_BOOT` | 串口日志开关 |
| — | `#deviceready 1` / `#ltecmd CMD_CLEAN_FW` | （注释） |
| 28 | `if6 CMD_BOOT` | IPv6 |
| 29 | `autowandetect CMD_BOOT` | WAN 自动探测 |
| — | `#wbd CMD_CLEAR` | （注释） |
| 30 | `dhcpd CMD_BOOT` | DHCP 服务 |
| 31 | `wlan CMD_BOOT` | WiFi |
| 32 | `ieee1905 CMD_BOOT` | ATDP / OWL |
| 33 | `httpd CMD_BOOT` | web |
| 34 | `upnp CMD_BOOT` | UPnP |
| 35 | `dnsmasq CMD_BOOT` | DNS/DHCP |
| 36 | `usbapp CMD_ACCOUNT_RESET` / `CMD_ACCOUNT_SET` / `CMD_FTP_START` / `CMD_SAMBA_START` / `CMD_MINIDLNA_START` | USB 服务 |
| 37 | `pc_list CMD_BOOT` | LAN 主机列表 |
| — | `#iptvled CMD_BOOT` | （注释） |
| 38 | `ipsecvpn CMD_BOOT` | IPsec |
| 39 | `dlna CMD_BOOT` | DLNA |
| 40 | `openvpn CMD_BOOT` | OpenVPN |
| 41 | `pptp CMD_BOOT` | PPTP |
| 42 | `l2tpd CMD_BOOT` | L2TP |
| 43 | `crond CMD_BOOT` | cron |
| 44 | `visualization CMD_BOOT` | 状态可视化 |
| 45 | `igmpproxy CMD_BOOT` | IGMP |
| 46 | `nspingd` | 连通性探测 |
| 47 | `autofw CMD_BOOT` | 自动升级检查 |
| 48 | `owl CMD_BOOT` | OWL/SON |
| — | `#wbd CMD_BOOT` | （注释） |
| 49 | `led power on` | LED |
| 50 | `embedur CMD_BOOT` | **云管理代理**（见 cloud-agent 文档） |

**观察**：

- 内核模块（9）**早于**网络接口（16–19），符合依赖顺序。
- `wlan`（31）在 `dhcpd`（30）之后、`httpd`（33）之前。
- `embedur` 是**最后**启动的 —— 它会等整机就绪再连云端。
- `wanmode` / `async_event` / `iptvled` / `wbd` 在这个机型上被禁用了。

---

## 3. 35 个 dbus agent（`/usr/agents/`）

`arca-agent-loader` 启动时扫描 `/usr/agents/*.so`，每个 `.so` 注册一个
`arca.dbus.<服务>` 接口：

```
arca-ECOmode-agent.so        arca-ecmh-agent.so        arca-misc-agent.so
arca-autofw-agent.so         arca-firewall-agent.so    arca-openvpn-agent.so
arca-autowandetect-agent.so  arca-httpd-agent.so       arca-owl-agent.so
arca-crond-agent.so          arca-ieee1905-agent.so    arca-pptp-agent.so
arca-ddns-agent.so           arca-igmpproxysnooping…   arca-qos-agent.so
arca-dhcp6c-agent.so         arca-l2tp-agent.so        arca-radvd-agent.so
arca-dhcp6d-agent.so         arca-l2tpd-agent.so       arca-syslog_ng-agent.so
arca-dhcpc-agent.so          arca-tr69-agent.so        arca-transmission…
arca-dhcpd-agent.so          arca-udevd-agent.so       arca-ula-agent.so
arca-dhcprelay-agent.so      arca-upnp-agent.so        arca-usbapp-agent.so
arca-dnsmasq-agent.so        arca-v6rd-agent.so        arca-wanppp-agent.so
arca-wlan-agent.so           arca-zebra-agent.so
```

调用方式：

```sh
mng_cli action <消息名>          # 执行 /usr/share/msg/<消息名>
# 或
dbus-arca-cli --command <服务> <CMD_*> ...
```

---

## 4. ★ 事件总线：`/usr/share/msg/`（210 个动作脚本）

每个文件就是一条“动作链”，语法：

```
arca.dbus.<服务>:<动作> [参数]
```

### 4.1 重启（`reboot`）

```
#arca.dbus.misc:CMD_COMMIT
arca.dbus.wlan:CMD_STOP
arca.dbus.misc:sleep 2
arca.dbus.misc:commit
arca.dbus.misc:syslog CMD_SAVE
arca.dbus.misc:sleep 2
arca.dbus.misc:reboot
```

即：**停 WiFi → 提交配置 → 存日志 → 重启**。

### 4.2 WAN 就绪（`sys_bridge_dhcp_done`）

```
arca.dbus.misc:wan CMD_WAN_START $(1)
arca.dbus.voip:CMD_WAN_START
arca.dbus.wlan:CMD_RESTART
arca.dbus.firewall:CMD_RESTART
arca.dbus.dhcpd:CMD_RESTART
arca.dbus.netbios:CMD_RESTART
arca.dbus.dnsmasq:CMD_RESTART
arca.dbus.misc:ntpclient CMD_RESTART
arca.dbus.igmpproxy:CMD_RESTART $(1)
```

### 4.3 链路事件

```
link_up      → link_state CMD_LINK_UP
eth_up       → homeplugd MSG_ETH_LINK_UP
vlan_up      → ...
```

### 4.4 消息文件分类（210 个）

| 前缀 | 数量级 | 内容 |
|---|---|---|
| `ui_*` | ~130 | web/TR-069 触发的配置动作（无线、WAN、VPN、QoS…） |
| `tr69_*` | 10 | TR-069 相关 |
| `wan*` / `dhcpc*` / `sys_ipv6*` | ~30 | WAN/DHCP/IPv6 状态机 |
| `wps` / `WPS_*` | 5 | WPS |
| `syslog_ng_*` | 5 | 日志 |
| `sys_boot` / `reboot` / `sys_release_memory` | — | 系统级 |
| `ui_usb_*` / `ui_l2tp*` / `ui_pptp*` / `ui_openvpn*` | — | 服务控制 |

> 这 210 个文件 = **这台设备的完整“可执行动作字典”**。
> 想知道某个配置改动会连带重启哪些服务，直接看对应的 `ui_*` 文件。

---

## 5. 进程监管

`/etc/pslist.conf`（`sysmonitor` 读取）：

```
midcore        0  "/usr/sbin/midcore"     异常退出→重启
mng            no "/usr/sbin/mng"         异常退出→重启
dbus-daemon    yes "/sbin/reboot"         异常退出→【直接重启整机】
pc_list_daemon 0  ...
eapd / nas / httpd / owl_monitor
```

★ **dbus-daemon 挂了会直接 reboot** —— 整个系统的编排都依赖 dbus，
没有 dbus 就没有服务控制。

---

## 6. 调试开关（对逆向很有用）

`/sbin/arc_action_debug.sh`：

```
ARC_ACTION_Debug=1   → touch /tmp/arca_action.log、/tmp/mng_action_trace
ARC_ACTION_Log=<路径> → 把动作日志写到指定文件
```

设置后，每一次 `mng_cli action` / dbus 动作都会留下 trace。
这是**不用改固件就能观察动作链**的最省事办法。

---

## 7. 安全观察

1. **telnetd / sshd 出厂都是关闭的**（`ARC_TELNETD_ENABLE=0`、`ARC_SSHD_Enabled=0`），
   但 `sys_boot` 里这两步是**启用状态**（只是脚本内部再判断开关）——
   一旦有人把配置改成 1，下次启动就会起 `telnetd -l /bin/sh`（root shell）。
2. **串口控制台**：`ttyS0::askfirst:/bin/login` —— 物理接触串口就能登录；
   `arc_console` 可以把 `/dev/console` 指向 `/dev/null` 静音。
3. **dbus 是单点**：`dbus-daemon` 异常 → 整机重启（`pslist.conf`）。
4. **动作脚本没有鉴权**：能执行 `mng_cli action <任意消息>` 就能触发对应服务；
   消息名本身不是秘密（210 个文件都在 rootfs 里）。
5. **`embedur` 最后启动**：即使你把前面的服务都停了，云代理仍会在最后尝试连出。

---

## 8. 证据索引

| 内容 | 位置 |
|---|---|
| 启动入口 | `/etc/inittab`（preinit 生成）、`/sbin/sysup` 字符串 |
| 启动动作表 | `/usr/share/msg/sys_boot` |
| 事件动作 | `/usr/share/msg/*`（210 个） |
| agent 列表 | `/usr/agents/*.so`（35 个） |
| 进程监管 | `/etc/pslist.conf` |
| 调试开关 | `/sbin/arc_action_debug.sh`（`ARC_ACTION_Debug`） |
| 开关默认值 | `.glbcfg`：`ARC_TELNETD_ENABLE=0`、`ARC_SSHD_Enabled=0` |
