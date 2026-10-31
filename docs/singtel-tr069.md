# Singtel Mesh Router 的 TR-069（CWMP）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/sbin/tr69`（555 KB ELF）、`/usr/sbin/tr69_trigger`、
> `/usr/share/msg/tr69_*`、`.glbcfg` 的 `ARC_TR69_*`
> 一句话：**这是一套完整的 Arcadyan CWMP 客户端，默认开启，ACS 是 Singtel 的
> `bs-hdm.singnet.com.sg`，出厂账号 `<vendor-user>/<vendor-password>`，每 45 秒 Inform 一次。**

---

## 1. 端点与默认值（`.glbcfg`）

| 键 | 出厂值 | 含义 |
|---|---|---|
| `ARC_TR69_EnableCWMP` | **1** | CWMP 开 |
| `ARC_TR69_URL` | `https://bs-hdm.singnet.com.sg/cwmpWeb/CPEMgt` | ACS |
| `ARC_TR69_Username` | `VENDOR_CREDENTIAL_HERE` | ACS 认证账号 |
| `ARC_TR69_Password` | `VENDOR_CREDENTIAL_HERE` | ACS 认证口令 |
| `ARC_TR69_PeriodicInformEnable` | **1** | 周期 Inform |
| `ARC_TR69_PeriodicInformInterval` | **45** 秒 | ★ 非常频繁 |
| `ARC_TR69_ConnectionRequestPort` | 30005 | ACS 反向连接端口 |
| `ARC_TR69_STUNEnable` | 1 | STUN 打洞 |
| `ARC_TR69_STUNServerPort` | 3478 | |
| `ARC_TR69_SSL_Method` | `TLSv1.2` | |
| `ARC_TR69_UpgradeAutoRebootEnable` | 0 | 升级后自动重启（默认关） |
| `ARC_TR69_FirstUseDate` | `0000-00-00T00:00:00` | 首次使用 |

包信息：

```
Package: tr69
Version: 0.1-1
Description: The tr69 client from Arcadyan Corporation for embedded Linux.
Architecture: brcm63xx
Depends: libxml, libhttpclt, lib-arc-com, arc-middle-mod-ccfgsal, libumng, udns ...
```

---

## 2. 传输与认证

`strings` 里能看到：

```
Init_SSLClient
libssl.so.1.0.0 / libsslap.so.0.1
SSLv3 / TLSv1.2
parse_digest_request / DigestCalcHA1 / DigestCalcResponse
Digest realm="%s", algorithm=MD5, qop=auth, nonce="%s"
```

即：

- **HTTPS（TLS 1.2）** 连 ACS；
- 支持 **HTTP Digest（MD5）** 认证；
- 反向连接（Connection Request）走 **30005** 端口，
  外部可达时 ACS 直接连回来；不可达时用 **STUN** 打洞。

---

## 3. 支持的 CWMP RPC

客户端里出现的 SOAP 方法：

```
Inform
GetRPCMethods
GetParameterNames
GetParameterValues
SetParameterValues
GetParameterAttributes
SetParameterAttributes
AddObject
DeleteObject
GetQueuedTransfers
ScheduleDownload / DeleteQueuedTransfer
RequestDownload
Download
Upload
Reboot
FactoryReset
ScheduleInform
Kicked
Fault
```

也就是说：**ACS 可以读/写几乎所有配置、增删对象、下发固件、重启、恢复出厂。**

---

## 4. 固件下载

`tr69` 里的下载相关字符串：

```
DownloadURL / DownloadTransports / DownloadAvailability
Download failure: unable to contact file server
Download failure: file corrupted
Download failure: firmware verification fail, wrong signature
RequestDownload
ScheduleDownload
```

结论：

- ACS 通过 `Download` RPC 下发固件；
- 本地会校验文件完整性和 **数字签名**（"wrong signature"）；
- 校验通过后写入镜像分区（走 `fw_upgrade` 那条链，见
  [singtel-firmware-update.md](singtel-firmware-update.md)）；
- `ARC_TR69_UpgradeAutoRebootEnable` 控制升级后是否自动重启（默认 0）。

---

## 5. ACS 能触发的本地动作

`/usr/share/msg/tr69_*` 一共 10 个，每个都是一条动作链：

| 消息 | 动作 |
|---|---|
| `tr69_wireless` | 停/起 WLAN（`wlan CMD_STOP/START`） |
| `tr69_wan` | 重配 WAN + GPIO + heartbeat + dhcpc + wanppp |
| `tr69_wanmac` | 改 WAN MAC 克隆 + 重配 WAN/DNS/UPnP |
| `tr69_lan` | 重启 DHCP / DHCP relay |
| `tr69_ntp` | 重启 ntpclient |
| `tr69_singleforward` | 停/起 sshd + 重启防火墙 |
| `tr69_spdsvc` | 触发 speed service |
| `tr69_stun` | 重启 TR-069 的 STUN 通道 |
| `tr69_factory_default_wlan` | 恢复 WLAN 出厂设置 |
| `tr69_embedUR` | 停/起 EmbedUR 云代理 |

> 这些就是 ACS 改了某个参数后，本机执行的“副作用”。
> 想知道某个 TR-069 参数会影响什么，看对应的 `tr69_*` 文件即可。

---

## 6. 参数树

`tr69` 里包含大量 TR-181/TR-098 参数名，例如：

```
DeviceInfo.Manufacturer / ManufacturerOUI / FirmwareVersion
DeviceInfo.HardwareVersion / SerialNumber / ModelName / ProductClass
InternetGatewayDevice.*
WiFi / WLANConfiguration / AccessPoint
IEEE11iAuthenticationMode / APWMMParameter
CaptivePortalURL / DownloadDiagnostics / DownloadURL
ConnectionRequestURL / ConnectionRequestUsername / ConnectionRequestPassword
ManagementServer.URL / Username / Password / PeriodicInformInterval
```

客户端启动时会把设备身份拼成一条 Inform：

```
manufacturer_name=[%s], manufacturer_oui=[%s], firmware_version=[%s],
boot_version=[%s], hardware_version=[%s], serial_number=[%s],
model_name=[%s], product_code=[%s], description=[%s]
```

---

## 7. `tr69_trigger`（本地触发工具）

`/usr/sbin/tr69_trigger` 通过消息队列（`msgget` / `msgsnd`）给 `tr69` 发命令：

```
reload
start
findntp
bootstrap
connreq
showstats
updateurl
```

`/sbin/arc_spdsvc_tr69` 也用 `tr69_trigger` 做测速。

---

## 8. 怎么关掉

```sh
mng_cli set ARC_TR69_EnableCWMP=0
mng_cli set ARC_TR69_STUNEnable=0
mng_cli commit
```

注意：**只改 `ARC_TR69_Enable` 可能不够** —— 客户端真正看的是
`ARC_TR69_EnableCWMP`。两者都设成 0 最稳。

---

## 9. 安全观察

1. **默认开启 + 固定账号**：`<vendor-user>/<vendor-password>`，ACS 地址固定。
   如果这个账号在 Singtel 侧是共享的，拿到它就是“云端管理权限”。
2. **每 45 秒 Inform**：设备会持续向 ACS 上报状态并拉取任务；
   流量不大，但意味着 **云端随时可以下发配置/固件**。
3. **ACS 能改一切**：WiFi、WAN、LAN、NTP、SSH、防火墙、固件、恢复出厂。
4. **反向连接 30005 + STUN**：即使设备在 NAT 后，ACS 也能连进来。
5. **固件下载有签名校验**（"wrong signature"），这一层是有效的；
   但签名公钥在固件里，属于厂商体系。
6. **TLS 1.2**，但客户端仍保留 SSLv3 的代码路径（`SSLv3` 字符串）——
   是否真的允许降级要看运行时配置，不能仅凭字符串下结论。

---

## 10. 证据索引

| 内容 | 位置 |
|---|---|
| CWMP 客户端 | `/usr/sbin/tr69`（555 KB） |
| 本地触发 | `/usr/sbin/tr69_trigger`（msgget/msgsnd） |
| ACS 动作 | `/usr/share/msg/tr69_*`（10 个） |
| 默认值 | `.glbcfg` 的 `ARC_TR69_*` |
| agent | `/usr/agents/arca-tr69-agent.so`（`arca.dbus.tr69`） |
| 证书目录 | `/usr/share/config/etc/config/cert/TR69/`（本版本为空） |
| 测速联动 | `/sbin/arc_spdsvc_tr69` |
