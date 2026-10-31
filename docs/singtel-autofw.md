# Singtel Mesh Router 的自动固件升级（`autofw`）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/sbin/autofw`（ELF，libcurl + json-c）、`/etc/autofw.conf`、
> `.glbcfg` 的 `ARC_SYS_AUTOFW_*`
> 一句话：**设备会按时间窗向 `firmware.singnet.com.sg` 查询新版本，
> 下载后调用 `fw_upgrade`，再按重启窗口自动重启。**

---

## 1. 配置

### `/etc/autofw.conf`（出厂模板）

```json
{
  "Url": "http://192.168.1.200",
  "SerialNum": "AVENDOR_BACKHAUL_PSK_HERE90",
  "ProductClass": "FVENDOR_BACKHAUL_PSK_HERE90",
  "CurrentVersion": "v1.00.00",
  "Interface1": "vlan20",
  "Seed": 3671539428,
  "BootUpCheckStartTime": 1,
  "BootUpCheckEndTime": 6,
  "PeriodCheckTime": 8,
  "FailRetryInterval": 10,
  "RebootDayOfWeek": 1,
  "RebootStartTime": 3,
  "RebootEndTime": 6,
  "MaximumCheckTimes": 1
}
```

> ★ 模板里的 `Url` 是 **`http://192.168.1.200`**（测试服务器），
> 运行时会被 `.glbcfg` 覆盖成正式地址。

### `.glbcfg`（运行时）

```
ARC_SYS_AUTOFW_Enable=1
ARC_SYS_AUTOFW_Url=https://firmware.singnet.com.sg
ARC_SYS_AUTOFW_BootUpCheckStartTime=1
ARC_SYS_AUTOFW_BootUpCheckEndTime=6
ARC_SYS_AUTOFW_PeriodCheckTime=8
ARC_SYS_AUTOFW_FailRetryInterval=10
ARC_SYS_AUTOFW_RebootDayOfWeek=1
ARC_SYS_AUTOFW_RebootStartTime=3
ARC_SYS_AUTOFW_RebootEndTime=6
ARC_SYS_AUTOFW_MaximumCheckTimes=1
```

含义：

| 字段 | 含义 |
|---|---|
| `BootUpCheckStart/EndTime` | 开机后允许检查的时间窗（小时） |
| `PeriodCheckTime` | 周期检查间隔（小时） |
| `FailRetryInterval` | 失败重试间隔 |
| `RebootDayOfWeek` / `RebootStart/EndTime` | 允许自动重启的窗口 |
| `MaximumCheckTimes` | 每次启动最多检查几次 |

---

## 2. 协议（从字符串还原）

`autofw` 用 **libcurl** 发 JSON：

```
Query URL[%s] with data[%s].
Content-Type:application/json;charset=UTF-8
```

端点：

```
%s/GetFirmwareVersion
%s/FirmwareDownloadResult
%s/FirmwareUpgradeResult
```

请求/响应里的 JSON 键：

```
"Current Version": "%s"
"New Version": "%s"
"Previous Version":"%s"
```

流程：

```
1. 在允许的时间窗内，POST 当前版本到 <Url>/GetFirmwareVersion
2. 如果 New Version != Current Version：
     - 下载固件
     - 调 /bin/fw_upgrade 写入
     - POST 结果到 <Url>/FirmwareUpgradeResult
3. 在 Reboot 窗口内重启
```

日志：

```
Firmware Check Start at [%s]...
New firmware version is %s
Downloading Firmware
Upgrading Firmware
Upgrade Firmware successfully
Reboot Window passed, schedule reboot again 10s later.
dlogger -f /data/reboot.log "Reboot (Auto Firmware Upgrade)."
```

状态文件：

```
/data/autofw_status
/data/autofw_reboot
/var/run/autofw.pid
```

---

## 3. 时间窗逻辑

- 启动时如果不在 `BootUpCheckStartTime..EndTime`，会打印：

```
Arrange to check Firmware [%ld] seconds later.
```

- 重启窗口：

```
RebootStartTime is less than RebootEndTime
Reboot Window passed, schedule reboot again 10s later.
Will reboot device in %d seconds later
```

- NTP 没同步时：

```
Didn't get NTP time, check 1min later
```

---

## 4. 安全观察

1. **默认开启**：`ARC_SYS_AUTOFW_Enable=1`，且 URL 是 HTTPS 正式地址。
2. **模板指向明文 HTTP 测试服务器**：`http://192.168.1.200`。
   如果运行时没被覆盖，流量是明文（但实际会被 glbcfg 覆盖）。
3. **自动下载 + 自动重启**：用户可能在不注意时被升级/重启。
4. **`Seed` 字段**：模板里有随机种子，可能是防重放/签名用；
   具体用途还没逐函数确认。
5. **最终仍走 `fw_upgrade`**：所以镜像签名校验（BCM tag 或 SHA-256+RSA）
   仍然生效；`autofw` 只是“下载器 + 调度器”。

---

## 5. 证据索引

| 内容 | 位置 |
|---|---|
| 程序 | `/usr/sbin/autofw` |
| 配置模板 | `/etc/autofw.conf` |
| 运行时配置 | `.glbcfg` 的 `ARC_SYS_AUTOFW_*` |
| 端点 | `%s/GetFirmwareVersion`、`FirmwareDownloadResult`、`FirmwareUpgradeResult` |
| 状态 | `/data/autofw_status`、`/data/autofw_reboot` |
| 升级执行 | `/bin/fw_upgrade`（见 singtel-firmware-update.md） |
