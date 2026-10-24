# Singtel Mesh Router 的 dbus 命令字典

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/agents/*.so`（35 个）、`/usr/share/config/etc/dbus-1/system.d/arca-agent-loader.conf`
> 工具：`/usr/sbin/dbus-arca-cli`

---

## 0. 一句话结论

所有服务都挂在 **system dbus** 上，接口名是 `arca.dbus.<服务>`：

```
dbus-arca-cli --command --dest=arca.dbus.firewall CMD_RESTART
dbus-arca-cli --enquire --dest=arca.dbus.dnsmasq STAT_AGENT
dbus-arca-cli --notify  --dest=arca.dbus.radvd CMD_QUIT
```

`arca-agent-loader` 启动时加载 `/usr/agents/*.so`，每个 `.so` 注册一个接口。
**35 个 agent、95 个唯一的 `CMD_*`**（各 agent 合计出现 250 处），全部列在下面。

---

## 1. `dbus-arca-cli` 用法

二进制里自带的 usage：

```
Usage: dbus-arca-cli <--enquire | --command | --notify>
                     [--dest=NAME] <VARIABLE[=VALUE] | COMMAND[=ARGUMENT]>
                     { [--dest=NAME] <VARIABLE[=VALUE] | COMMAND[=ARGUMENT]> ... }

Note: There MUST NOT be space or tab character before or after equal sign.

Examples:
  dbus-arca-cli --enquire --dest=arca.dbus.dnsmasq STAT_AGENT
  dbus-arca-cli --command --dest=arca.dbus.dnsmasq "CMD_SLEEP 3" \
                --dest=arca.dbus.radvd "CMD_SLEEP 1"
  dbus-arca-cli --notify CMD_QUIT
  dbus-arca-cli --notify --dest=arca.dbus.dnsmasq STAT_AGENT \
                --dest=arca.dbus.radvd CMD_QUIT
```

三种模式：

| 模式 | 作用 |
|---|---|
| `--enquire` | 查询变量（如 `STAT_AGENT`） |
| `--command` | 调方法（带返回） |
| `--notify` | 发信号（不等返回） |

dbus 路径固定：`/arca/dbus/instance`。

> **注意**：`--dest` 必须写在**第一条参数**；`=` 两边不能有空格。

---

## 2. 35 个 agent 的命令表

| agent `.so` | 接口 | 命令 |
|---|---|---|
| `arca-autofw-agent` | `arca.dbus.autofw` | BOOT / START / STOP / RESTART / QUIT / TRIGGER |
| `arca-autowandetect-agent` | `arca.dbus.autowandetect`（+`misc`） | BOOT / BOOTSTRAP / IFSEQ / DSL_MOD / DSL_INET_NLED_TOGGLE / USB_CONNECT / START / STOP / RESTART / QUIT |
| `arca-crond-agent` | `arca.dbus.crond` | BOOT / START / STOP / RESTART / QUIT |
| `arca-ddns-agent` | `arca.dbus.ddns` | BOOT / START / STOP / RESTART / QUIT / SLEEP / UPDATE |
| `arca-dhcp6c-agent` | `arca.dbus.dhcp6c` | BOOT / START / STOP / RESTART / QUIT / RENEW / RELEASE |
| `arca-dhcp6d-agent` | `arca.dbus.dhcp6d` | BOOT / START / STOP / RESTART / QUIT |
| `arca-dhcpc-agent` | `arca.dbus.dhcpc` | BOOT / START / STOP / RESTART / QUIT / DHCPC_RENEW / DHCPC_RELEASE / DHCPC_IPTV_UNI_REQUEST / DHCPC_IPTV_UNI_RELEASE / BRIDGE_RESTART / BRIDGE_STOP / BRIDGE_RELEASE / DETECT_STOP / 6RD_RESTART |
| `arca-dhcpd-agent` | `arca.dbus.dhcpd` | BOOT / START / STOP / RESTART / QUIT / BRIDGE_RESTART / DEL_LEASE / WRITE_DHCPD_CLIENTS |
| `arca-dhcprelay-agent` | `arca.dbus.dhcprelay` | BOOT / START / STOP / RESTART / QUIT |
| `arca-dnsmasq-agent` | `arca.dbus.dnsmasq` | BOOT / START / STOP / RESTART / QUIT / SLEEP |
| `arca-ecmh-agent` | `arca.dbus.ecmh` | BOOT / START / STOP / RESTART / QUIT / SLEEP |
| `arca-ECOmode-agent` | `arca.dbus.ECOmode` | BOOT / START / STOP / RESTART / QUIT / ECO_PBC / TIME_CHANGE |
| `arca-firewall-agent` | `arca.dbus.firewall` | RESTART / QUIT（内部直接调 `arc_firewalld`） |
| `arca-httpd-agent` | `arca.dbus.httpd` | BOOT / START / STOP / RESTART / RELOAD / QUIT |
| `arca-ieee1905-agent` | `arca.dbus.ieee1905` | BOOT / START / STOP / RESTART / QUIT |
| `arca-igmpproxysnooping-agent` | `arca.dbus.igmpproxy` | BOOT / START / STOP / RESTART / QUIT |
| `arca-l2tp-agent` | `arca.dbus.l2tp` | BOOT / START_L2TP / STOP_L2TP / RESTART_L2TP / DEL_L2TP / UPDATE_L2TP / QUIT |
| `arca-l2tpd-agent` | `arca.dbus.l2tpd`（+`ipsecvpn`） | BOOT / START / STOP / RESTART / QUIT / UPDATE_L2TPD_CHAP |
| `arca-misc-agent` | `arca.dbus.misc` | ★ 特殊：按 `<脚本名> <CMD_*>` 调 `/sbin/arc_*`（见 §3） |
| `arca-openvpn-agent` | `arca.dbus.openvpn` | BOOT / START / STOP / QUIT / START_OVPNC / STOP_OVPNC / RESTART_OVPNC / DEL_OVPNC / UPDATE_OVPNC / START_OVPND / STOP_OVPND / RESTART_OVPND / UPDATE_OVPND / UPDATE_OVPND_PASSWD |
| `arca-owl-agent` | `arca.dbus.owl` | BOOT / START / STOP / RESTART / QUIT |
| `arca-pptp-agent` | `arca.dbus.pptp` | BOOT / START / STOP / QUIT / START_PPTP / STOP_PPTP / RESTART_PPTP / DEL_PPTP / UPDATE_PPTP / START_PPTPD / STOP_PPTPD / RESTART_PPTPD / UPDATE_PPTPD / UPDATE_PPTPD_CHAP |
| `arca-qos-agent` | `arca.dbus.qos` | BOOT / START / STOP / RESTART / QUIT |
| `arca-radvd-agent` | `arca.dbus.radvd` | BOOT / START / STOP / RESTART / QUIT / SLEEP |
| `arca-syslog_ng-agent` | `arca.dbus.syslog_ng` | BOOT / START / STOP / RESTART / QUIT / SAVE / CLEAR |
| `arca-tr69-agent` | `arca.dbus.tr69` | BOOT / START / STOP / RESTART / QUIT / DEFAULTS / REINIT_PORTMAPPING |
| `arca-transmission-agent` | `arca.dbus.transmission` | BOOT / START / STOP / RESTART / QUIT |
| `arca-udevd-agent` | `arca.dbus.udevd` | BOOT / START / STOP / RESTART / QUIT |
| `arca-ula-agent` | `arca.dbus.ula` | BOOT / START / STOP / RESTART |
| `arca-upnp-agent` | `arca.dbus.upnp` | BOOT / START / STOP / RESTART / QUIT / WAN_UPDATE / WAN_IFUPDATE |
| `arca-usbapp-agent` | `arca.dbus.usbapp` | ★ 26 个：ACCOUNT_BOOT / ACCOUNT_SET / ACCOUNT_RESET / ACTION_UNMOUNT / ACTION_USB30TO20 / DLNA_START/STOP/RESTART/UPDATE/RESCAN / FTP_START/STOP/RESTART/UPDATE / LPD_START/STOP/RESTART / MINIDLNA_START/STOP/RESTART / SAMBA_START/STOP/RESTART/UPDATE/IFMODIFY / QUIT |
| `arca-v6rd-agent` | `arca.dbus.v6rd` | BOOT / START / STOP / RESTART / QUIT / CONNECT / DISCONNECT / RECONNECT |
| `arca-wanppp-agent` | `arca.dbus.wanppp` | BOOT / START / STOP / RESTART / QUIT / STAGE2 |
| `arca-wlan-agent` | `arca.dbus.wlan` | BOOT / START / STOP / RESTART / QUIT / ACS_CHANGE / WL_SPEC / WPS_PUSHBUTTON / WPS_ENTERPIN / WPS_CANCEL |
| `arca-zebra-agent` | `arca.dbus.zebra` | BOOT / START / STOP / RESTART / QUIT |

---

## 3. `arca.dbus.misc` 的特殊分派

`misc` agent 不按 `CMD_*` 分派，而是把**第一个参数当脚本名**：

```
arca.dbus.misc:sysctrl CMD_BOOT     → /sbin/arc_sysctrl CMD_BOOT
arca.dbus.misc:mount CMD_BOOT       → /sbin/arc_mount CMD_BOOT
arca.dbus.misc:wan CMD_WAN_UPDATE   → /sbin/arc_wan CMD_WAN_UPDATE
arca.dbus.misc:led power on         → /sbin/arc_led ...
```

所以 `misc` 的“命令字典”其实就是 `/sbin/arc_*` 这一整套脚本：

```
arc_sysctrl arc_mount arc_glbcfg arc_modules arc_switch arc_vlan
arc_wan arc_if6 arc_lan arc_bridge arc_telnetd arc_sshd arc_wlan
arc_wbd arc_qos arc_firewalld arc_firewall6 arc_usb ... (见 §4)
```

`sys_boot` 里绝大多数条目走的都是这条路径。

---

## 4. 常用命令示例

```sh
# 重启防火墙（重新生成 /tmp/.ipt）
dbus-arca-cli --command --dest=arca.dbus.firewall CMD_RESTART

# 重启 WiFi（会短暂断网）
dbus-arca-cli --command --dest=arca.dbus.wlan CMD_RESTART

# 让 dnsmasq 重启
dbus-arca-cli --command --dest=arca.dbus.dnsmasq CMD_RESTART

# 触发 WPS PBC
dbus-arca-cli --command --dest=arca.dbus.wlan CMD_WPS_PUSHBUTTON

# 查询 agent 状态
dbus-arca-cli --enquire --dest=arca.dbus.dnsmasq STAT_AGENT

# 通过 misc 调脚本
dbus-arca-cli --command --dest=arca.dbus.misc "led power on"
```

---

## 5. 安全观察

1. **dbus policy 是 `context="default"` 全放行**：

   ```xml
   <policy context="default">
     <allow own="arca.dbus.firewall"/>
     <allow send_destination="arca.dbus.firewall"/>
     <allow receive_sender="arca.dbus.firewall"/>
     <allow send_path="/arca/dbus/instance"/>
   </policy>
   ```

   **没有 uid/gid 限制** —— 任何本地进程（包括被攻陷的 httpd、USB 服务、
   第三方 agent）都能调这些方法。

2. **接口数量远大于实际服务**：policy 里有 **104 个** `arca.dbus.*`，
   但设备只装了 35 个 agent —— 其余是 SDK 里其他项目的接口定义，
   没有对应 `.so`，属于“声明了但不可用”。

3. **`--notify CMD_QUIT` 可以广播**：不带 `--dest` 时会发给所有订阅者，
   可能导致多个服务同时退出（再由 `sysmonitor` 拉起来）。

4. **没有鉴权、没有速率限制**：`CMD_RESTART` 连发会反复重启服务；
   `CMD_STOP` 可以让 WiFi/防火墙下线，直到 `sysmonitor` 或下次动作把它拉回来。

5. **`misc` 的脚本名是可控字符串**：如果调用方没有过滤，理论上可以调
   `/sbin/arc_*` 里的任意脚本。实际上这些脚本本身也只做固定动作。

---

## 6. agent 框架 API（`libagent-api.so`）

所有 `arca-*-agent.so` 都链接这个库：

```
agent_register / agent_unregister
agent_message_loop
agent_send_command / agent_send_command2
agent_send_enquire / agent_send_enquire2
agent_send_notify
agent_forward
agent_set_timer
```

内部处理器：

```
_command_handler
_enquire_handler
_notify_handler
_forward_handler
```

dbus 细节：

```
bus name: arca.dbus.service
path:     /arca/dbus/instance
日志:     /tmp/arca_action.log
```

`libagent-shared.so` 提供：

```
dns_to_resolv / dns_to_resolv2      写 resolv.conf
is_guestnetwork_enabled             查 guest 网络
```

## 7. `arca-agent-loader`

```
Usage: arca-agent-loader [path]
```

- 默认扫描 `/usr/agents/*.so`，`dlopen` 后调用里面的注册函数；
- 成功后 touch `/tmp/.arca-agent-loader.ok`；
- 环境变量 `ARC_AGENT_DEBUG` 控制调试；
- 启动日志：`Try to load agent : %s`。

★ 安全点：loader 会 `dlopen` 指定目录下的 `.so` ——
如果 `path` 参数可控且目录可写，等于任意代码执行（需要 root）。

---

## 8. 证据索引

| 内容 | 位置 |
|---|---|
| 命令行工具 | `/usr/sbin/dbus-arca-cli`（usage 字符串） |
| agent 目录 | `/usr/agents/*.so` |
| dbus 策略 | `/usr/share/config/etc/dbus-1/system.d/arca-agent-loader.conf`（104 个接口） |
| 启动动作 | `/usr/share/msg/sys_boot`（见 boot 文档） |
| misc 脚本 | `/sbin/arc_*` |
