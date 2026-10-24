# Singtel 的通用库：validation / conversion / shared / ArcCom

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`libarc-validation.so`、`libarc-conversion.so`、`libarc-shared.so`、`libArcCom.so`
> 作用：这些库被 httpd / mng / tr69 / dbus agent 共用，负责校验、转换、CRC、IP、时间。

---

## 1. `libarc-validation.so`

导出：

```
init_validator_table / validation_table_init / validation_table_exit
get_validation / get_validator / validate / release_validation
ParseStringWithQuotes / trim_tail / skip_space / escape / find_space
dlist_*（双向链表）
```

规则来源：

```
/etc/validation_rules.conf
```

> **注意**：这个文件在 rootfs 里**不存在**，说明规则表可能是
> 运行时生成、或在 `/data` 里、或编译进二进制。

字符串里能看到的规则类型：

```
ipv4-range
multiPort
pppIdleTime
Range
script
Invalid rule (%s).
```

即：IP 段、多端口、PPP 空闲时间、数值范围、脚本校验。

---

## 2. `libarc-conversion.so`

导出：

```
init_converter_table / conversion_table_init / conversion_table_exit
get_conversion / get_converter / convert / release_conversion
```

和 validation 同一套“表 + 规则”模式，负责把一种表示转换成另一种
（例如时间/单位/枚举名 ↔ 数值）。

---

## 3. `libarc-shared.so`（工具函数大杂烩）

### 3.1 Buffer / 参数解析

```
Buffer_Init / Alloc / Realloc / Destroy
Buffer_Cat / Cpy / DataCat / DataCpy / IsEmpty / GetSpaceSize
arg_parser_init / arg_parser_init_reserve_empty / arg_parser_destory
checkStringToCMD
```

### 3.2 CRC / MAC / IP

```
crc8 / crc16 / crc32
ether_atoe / ether_etoa
get_ip_list_by_mac
get_single_ip / get_mac / get_netip
get_linklocal_ipv6addr
```

### 3.3 CTF（Broadcom Cut-Through Forwarding）

```
ctf_add_filter
ctf_set_wanip
ctf_ipc_del_by_ip_range / by_mac / by_port_range
clear_ctf_entries
```

### 3.4 其它

```
check_if_up
buf_to_file / append_to_file
get_sys_uptime / getsysuptime
```

---

## 4. `libArcCom.so`

### 4.1 IP 工具

```
utilIpStr2Ip / utilIp2Str / utilIp2Val
utilIpCmp / utilIpCpy
utilIpInSameSubnet / utilIpIsSameSubnetAddr
utilIpSubnetAddr / utilIpSubnetBcAddr / utilIpIsZero
```

### 4.2 时间工具

```
osTime / osTimeSec / osTimeMSec / osTimeCSec / osTimeTick
osTimeMSec2Tick / osTimeTicksPerSec / osTimeIsUp
Osix_GetKernelTime
utilElapsedTime（/tmp/tmputilElapsedTime）
```

### 4.3 平台信息

```
drvDslInfoGet
drvEthPhyStatus
drvLteInfoGet
drvSysVerGet
drvUsbAdmin
```

### 4.4 其它

```
md5Init / md5Update / md5Final
CreatePIDFile
hal_OsixSemTake / Give
_osItcMap*（共享内存/ITC 映射）
lib_arc_com_parse_proc_device_file_to_create_char_device_node
```

---

## 5. 这些库在哪些地方被用

| 库 | 典型调用方 |
|---|---|
| `libarc-validation` | httpd（表单校验）、mng（配置 set 校验） |
| `libarc-conversion` | httpd / mng（单位、枚举转换） |
| `libarc-shared` | 几乎所有 `arc_*` 服务、CTF 相关 |
| `libArcCom` | 驱动/平台信息、IP 工具、时间工具 |

---

## 6. 安全观察

1. **`crc8/crc16/crc32` 是通用实现**，可用于校验固件/配置块（但不是签名）。
2. **`ctf_ipc_del_by_mac/ip_range/port_range`** 说明 CTF 加速表可以被用户态增删，
   配置错误可能导致流量绕过防火墙。
3. **`utilIp*` 是手写 IP 解析**，这类函数历史上容易出现边界/溢出问题。
4. **`libarc-validation` 依赖外部规则文件**，如果 `/data` 里的规则被改，
   表单校验行为会变。
5. **`drvLteInfoGet` / `drvDslInfoGet`** 直接读驱动信息，暴露链路状态。

---

## 7. 证据索引

| 内容 | 位置 |
|---|---|
| 校验 | `/usr/lib/libarc-validation.so`（`/etc/validation_rules.conf`） |
| 转换 | `/usr/lib/libarc-conversion.so` |
| 通用 | `/usr/lib/libarc-shared.so`（CRC/IP/CTF/Buffer） |
| 平台 | `/usr/lib/libArcCom.so`（utilIp/osTime/drv*） |
