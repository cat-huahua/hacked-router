# Singtel 的 Broadcom CMS 数据模型与 `consoled` 控制台

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`libcms_core.so`、`libcms_dal.so`、`libcms_qdm.so`、`libcms_cli.so`、
> `libcms_util.so`、`/bin/consoled`、`/usr/sbin/cfgview`
> 一句话：**除了 Arcadyan 的 `.glbcfg`，设备里还有一套 Broadcom CMS
> 配置数据模型（TR-098/181），并带一个认证控制台 `consoled`。**

---

## 1. 两套配置系统

| 系统 | 存储 | 入口 | 用途 |
|---|---|---|---|
| **Arcadyan `.glbcfg`** | `/etc/config/.glbcfg` + `pricfg` 分区 | `mng_cli` → `midcore` | 设备自身所有配置 |
| **Broadcom CMS** | config flash（CRC 头） | `consoled` / `cfgview` / TR-069 | TR-098 数据模型、TR-069 参数 |

两者并存；TR-069 参数通过 CMS 映射到实际网络配置。

---

## 2. CMS 各库

| 库 | 作用 |
|---|---|
| `libcms_core.so` (766 KB) | 核心：MDM 数据模型、对象、配置 flash、锁、安全日志 |
| `libcms_dal.so` (220 KB) | 数据访问层：WAN/LAN/DNS/syslog/login 配置 |
| `libcms_qdm.so` (86 KB) | 查询/映射：接口 full path ↔ ifname、VLAN、DHCP 选项 |
| `libcms_cli.so` (107 KB) | CLI 命令实现（`cliCmd_*`） |
| `libcms_util.so` (181 KB) | 镜像/配置校验（见 firmware-update 文档） |
| `libcms_msg.so` | 与 `smd` 的消息通信 |

### `libcms_core` 的主要函数组

```
cmsMdm_*   数据模型（path descriptor / IID / 对象）
cmsObj_*   对象实例（add/get/set/delete/dump）
cmsMgm_*   配置 flash（read/save/validate/invalidate）
cmsLck_*   锁（acquire/release/dump）
cmsLog_*   安全日志（cmsLog_security/getSecurityLog）
```

### 配置 flash 格式（反汇编确认）

真正的头部字符串在 `.rodata`：

```
<compressed alg=lzw len=<len>>
<crc=0x<hex>>
```

所以一个配置块的布局是：

```
[可选] <compressed alg=lzw len=N>      ← 仅当内容被 LZW 压缩
<crc=0xXXXXXXXX>                        ← CRC32（crc_getCrc32）
<文本配置>                              ← NUL 结尾，MDM 解析
```

关键函数/行为：

| 函数 | 行为 |
|---|---|
| `cmsMgm_validateConfigBuf` | 检查最后一个字节是否 0，不是就 realloc 补 NUL；然后 `mdm_validateConfigBuf` |
| `oal_readConfigFlashToBuf` | 从 config flash 读（`devCtl_boardIoctl(0xC0184201)`），解析上面的头 |
| `cmsLzw_decode` / `cmsLzw_initDecoder` | **LZW 解压**（不是 zlib！） |
| `cmsLzw_initEncoder` / `cmsLzw_encode` | 写入前 LZW 压缩 |
| `crc_getCrc32` | CRC32 校验 |
| `cmsMgm_saveConfigToFlash` | 写回 primary config flash |

错误串：

```
could not allocate %d bytes for compressed buf
compressed len=%d uncompressed len=%d
crc header detected, crc=0x%x
crc header detected (after compression header), crc=0x%x
crc check for config %s failed, calculated=0x%x headerCrc=0x%x
cannot fit config buf into flash, max=%d got=%d
```

> **注意**：这里用的是 **LZW**，不是 zlib/gzip —— 和 `.config.tgz` 那条链不同。

---

## 3. `consoled`：CMS 控制台

`/bin/consoled`：

```
usage: consoled [-v num] [-m shmId]
       v: set verbosity, where num==0 is LOG_ERROR,
          1 is LOG_NOTICE, all others is LOG_DEBUG
```

流程：

```
cmsLog_initWithName / cmsLog_setDestination
cmsMdm_initWithAcc
cmsMsg_initWithFlags
cmsLck_acquireLockWithTimeoutTraced
cmsCli_authenticate      ← 认证
cmsCli_printWelcomeBanner
cmsCli_run               ← 交互式 CLI
```

错误路径：

```
could not connect to CMS smd (ret=%d) == drop to shell for debug
could not get shmId from smd (r2=%d) == drop to shell for debug
failed to get lock, ret=%d
get of CONSOLED_CFG object failed, ret=%d
```

★ **“drop to shell for debug”**：如果 `smd` 连不上，`consoled` 可能直接落到 shell。
这需要能启动 `consoled`（串口/tty），不是远程入口，但值得记录。

### `libcms_cli` 的命令（90 个导出函数）

按功能分组：

**配置类**

```
cliCmd_configLanIp_igd / _dev2
cliCmd_deleteLanIp_igd / _dev2
cliCmd_configDhcpClient_igd / _dev2
cliCmd_configDhcpServer_igd / _dev2
cliCmd_showDhcpServer_igd / _dev2
cliCmd_updateDhcpServer_igd / _dev2
```

**显示类**

```
processLanHostsCmd      LAN 主机列表
processWanCmd           WAN 状态
processUptimeCmd        运行时长
processMeminfoCmd       内存信息
processSwVersionCmd     软件版本
processSyslogCmd        系统日志
processMdmCmd           MDM 数据模型
processVirtualServerCmd 虚拟服务器（端口转发）
cli_wanShowInterfaces_igd / _dev2
cli_wanShowServices / Sub
cli_wanShowDslServices
virtualServerShow / virtualServerEnableDisable
```

**调试/工厂类**

```
cmdArpAddDel / cmdArpHelp                  ARP 表操作
cmdBtrmCfgHelp / cmdBtrmMrktId /
cmdBtrmSingleBit                           bootrom (btrm) 配置
cmdDefaultGatewayHelp / cmdDhcpServerHelp / cmdDnsHelp
cli_processHiddenCmd                       ★ 隐藏命令入口
cli_sendMsgToSsk                           ＊ 发消息给 SSK
cli_waitForInputAvailable / cli_waitForContinue
```

**校验器**（说明支持哪些字段）

```
cli_isIpAddress / cli_isMacAddress / cli_isNumber
cli_isValidVpi / cli_isValidVci / cli_isValidVlanId
cli_isValidWanId / cli_isValidWanServiceName
cli_isValidPppUserName / cli_isValidPppPassword
cli_isValidL2IfName_dev2 / _igd
cli_isValidIdleTimeout / cli_isValidService / cli_isValidState
```

> `cli_processHiddenCmd` 是另一条隐藏命令路径；具体命令词表没有导出符号，
> 需要看 `libcms_cli.so` 内部字符串（目前只确认它存在）。

---

## 4. `cfgview`

`/usr/sbin/cfgview` 是一个更简单的工具：

```
dump
save
reload
Error: configure file is not exist!!
Can not open configure file
```

用来直接查看/保存 CMS 配置文件。

---

## 5. 安全日志

`libcms_core` 提供：

```
cmsLog_security
cmsLog_getSecurityLog
cmsLog_printSecurityLog
cmsLog_resetSecurityLog
```

即 Broadcom CMS 自带安全日志（登录失败、配置变更等），
可通过 CMS CLI 或 TR-069 读取。

---

## 6. 安全观察

1. **`consoled` 有认证**（`cmsCli_authenticate`），但认证实现和凭据来源未逐函数确认。
2. **“drop to shell for debug”**：smd 异常时可能落到 shell，属于本地/串口风险。
3. **CMS 配置 flash 有 CRC**，但 CRC 只防损坏，不防篡改（无签名）。
4. **两套配置系统**意味着同一个设置可能有两份来源（`.glbcfg` 与 CMS），
   改错一边可能被另一边覆盖。
5. **安全日志**可用于审计，但也可能被 `cmsLog_resetSecurityLog` 清空。

---

## 7. 证据索引

| 内容 | 位置 |
|---|---|
| CMS 核心 | `/lib/libcms_core.so`（`cmsMdm_*`/`cmsObj_*`/`cmsMgm_*`） |
| 配置 flash CRC | `addCrcHeader`、`crc header detected`、`compressed header detected` |
| 控制台 | `/bin/consoled`（`cmsCli_authenticate`/`cmsCli_run`） |
| CLI 命令 | `/lib/libcms_cli.so`（`cliCmd_*`） |
| 简单查看 | `/usr/sbin/cfgview`（dump/save/reload） |
| 安全日志 | `cmsLog_security` / `cmsLog_getSecurityLog` |
