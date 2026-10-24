# TR-069 的参数树（TR-098 + TR-181 + Singtel 扩展）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/sbin/tr69` 的完整路径字符串
> 结果：**203 条完整参数路径**，同时支持
> `InternetGatewayDevice.*`（TR-098）和 `Device.*`（TR-181）。

---

## 1. 双数据模型

| 模型 | 根 | 例子 |
|---|---|---|
| TR-098 | `InternetGatewayDevice.` | `InternetGatewayDevice.LANDevice.1.…` |
| TR-181 | `Device.` | `Device.WiFi.SSID.1.…` |

同一功能两套路径都有，ACS 用哪套都能读/写。

---

## 2. 按顶层分组（203 条路径）

| 前缀 | 数量 |
|---|---:|
| `InternetGatewayDevice.WANDevice.1` | 16 |
| `InternetGatewayDevice.LANDevice.1` | 16 |
| `Device.Bridging.Bridge` | 16 |
| `Device.IP.Interface` | 12 |
| `Device.Ethernet.Interface` | 10 |
| `Device.WiFi.SSID` | 9 |
| `Device.WiFi.AccessPoint` | 7 |
| `Device.Ethernet.Link` | 7 |
| `InternetGatewayDevice.X_SINGTEL_COM_Channel_Capacity_Diagnostic` | 10 |
| `Device.WiFi.Radio` | 5 |
| `Device.IP.Diagnostics` | 5 |
| `Device.Routing.Router` | 4 |
| `Device.PPP.Interface` | 4 |
| `Device.DHCPv4.Client` | 3 |
| `InternetGatewayDevice.Services.VoiceService` | 2 |
| `Device.Firewall.Chain` | 2 |
| `Device.PTM.Link` / `Device.ATM.Link` / `Device.DHCPv6.Client` | 各 2 |

---

## 3. 标准参数组

```
Device.DeviceInfo.*                型号/序列号/软件版本/进程状态
Device.GatewayInfo.*               ManufacturerOUI / ProductClass / SerialNumber
Device.Ethernet.Interface.*        LAN1..LAN4
Device.Ethernet.Link.*             LAN / WAN
Device.Bridging.Bridge.*           br0 的 Port 1..7
Device.IP.Interface.*              IP 接口
Device.IP.Diagnostics.*            IPPing / TraceRoute / Download/UploadDiagnostics
Device.DHCPv4.Client.*             WAN 的 DHCP 客户端
Device.DHCPv4.Server.Pool.*        LAN DHCP 池
Device.DHCPv6.Client.*
Device.PPP.Interface.*
Device.WiFi.Radio.* / SSID.* / AccessPoint.*
Device.Routing.Router.*
Device.Firewall.Chain.* / Level.*
Device.Hosts.Host.*                LAN 主机表
Device.DSL.Channel.* / PTM.Link.* / ATM.Link.*
Device.DSLite.*
```

---

## 4. ★ Singtel 厂商扩展（`X_SINGTEL_COM_*`）

这些是 Arcadyan/Singtel 自己加的 TR-069 对象：

| 对象 | 作用 |
|---|---|
| `InternetGatewayDevice.X_SINGTEL_COM_WEB_Login.` | **Web 登录相关参数** |
| `InternetGatewayDevice.X_SINGTEL_COM_Telnet.` | **Telnet 开关** |
| `InternetGatewayDevice.X_SINGTEL_COM_UPnPIGD.` | UPnP IGD |
| `InternetGatewayDevice.X_SINGTEL_COM_SpeedService.` | 测速服务（`ResultHistory`） |
| `InternetGatewayDevice.X_SINGTEL_COM_Channel_Capacity_Diagnostic.` | 信道容量诊断（`Result24G` / `Result5G`） |

也就是说：**ACS 可以通过 `X_SINGTEL_COM_Telnet` 打开 telnet**，
通过 `X_SINGTEL_COM_WEB_Login` 改 Web 登录相关设置 —— 这是比标准 TR-098
更直接的管理面。

---

## 5. 与 `arc_cfg` 的关系

`tr69` 对标准参数的读写最终调用 `arc_cfg_get/set`（见
[singtel-tr069-mapping.md](singtel-tr069-mapping.md)），
落到 `.glbcfg` 的具体键；厂商扩展也走同一套。

---

## 6. 安全观察

1. **双模型意味着两套写路径**：ACS 可以用 TR-098 或 TR-181 改同一设置。
2. **厂商扩展包含 Telnet/Web 登录**：`X_SINGTEL_COM_Telnet` 是高风险对象。
3. **`Device.Hosts.Host.*`** 暴露 LAN 主机（MAC/IP/主机名）。
4. **`Device.IP.Diagnostics.*`** 可被 ACS 用来发起 ping/traceroute/带宽测试。
5. **`X_SINGTEL_COM_SpeedService.ResultHistory`** 保存测速历史。

---

## 7. 证据索引

| 内容 | 位置 |
|---|---|
| 路径字符串 | `/usr/sbin/tr69`（203 条 `InternetGatewayDevice.*`/`Device.*`） |
| 配置 API | `arc_cfg_get/set` |
| 厂商扩展 | `X_SINGTEL_COM_WEB_Login` / `_Telnet` / `_UPnPIGD` / `_SpeedService` / `_Channel_Capacity_Diagnostic` |
