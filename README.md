# hacked-router · wifi hacker

家里几台网络设备的**本地 API 逆向与脚本化控制**工具集。

不是"破解别人的网" —— 是**自己家的设备，厂商给的界面太烂或者有 bug，所以直接跟它的 API 说话**。

> **⚠️ 本仓库里的凭证已全部替换成占位符**（`WIFI_PASSWORD_HERE` / `ROUTER_PASSWORD_HERE` /
> `FACTORY_PASSWORD_HERE`），设备 MAC 和主机名也泛化成了示例值。
> **要拿去用，先把这些换成你自己的。** 详见下面「怎么用」。

## ⚖️ 许可证与使用范围

[**MIT License**](LICENSE) © 2026 cat-huahua —— 随便用、改、分发，但**不附带任何担保**。

**⚠️ 使用前请先读 [NOTICE.md](NOTICE.md)（使用范围与免责）和
[THIRD-PARTY.md](THIRD-PARTY.md)（第三方材料）**。要点：

- 这些工具**只对你本人拥有、或已获明确书面授权的设备**使用。
- 许可证授予的是**著作权许可**，它**不能、也不构成访问授权** ——
  拿它去碰别人的网络/设备，可能触犯新加坡《滥用电脑法》、美国 CFAA、
  英国 CMA、中国刑法 285/286 条等，**责任由使用者自负**。
- **MIT 只覆盖作者自己写的代码与文档。** `singtel_mesh/pages/` 里的设备界面
  文件著作权属 **Arcadyan / Singtel**，**不在 MIT 授权范围内** ——
  收录目的仅为互操作性与维修（详见 THIRD-PARTY.md）。
- 仓库内**不含**任何真实凭据、密钥、厂商固件或配置备份。
- 作者不保证本软件在任何司法辖区的使用是合法的；**这不是法律意见**。
- **如果你是权利人**：开个 Issue 或发封邮件就行，**先沟通，不用先发律师函**。

---

## 覆盖的设备

| 设备 | 地址 | 干了什么 |
|---|---|---|
| **华为 Q2S 主路由** | `192.168.3.1` | 全功能 REST API：DHCP 静态绑定、改设备名、读主机表 |
| **Singtel Mesh（Arcadyan WE410443-ST）** | `192.168.3.2` + 3 台卫星 | 逆向登录算法、WiFi 配置写入、节点重命名、**登录锁机制** |
| **NETGEAR R7800** | `192.168.3.3` | SOAP API（`admin`/密码 → JWT），只能读不能改 LAN |
| **Singtel 云端** | `mqtt.wifi-analytics.singnet.com.sg` | DNS 劫持 + 自签证书**冒充云端**，接管设备的 MQTT 通道 |

---

## 怎么用（填你自己的凭证）

```bash
git clone <this-repo> && cd hacked-router
grep -rn "PASSWORD_HERE" .          # 找出所有要填的地方
# 把 WIFI_PASSWORD_HERE / ROUTER_PASSWORD_HERE / FACTORY_PASSWORD_HERE 换成真值
# 把 hw_q2s/router.py 里的 TARGET 示例表换成你家的 MAC
```

---

## 各设备的关键结论

### 华为 Q2S（`hw_q2s/`）

- 走 SCRAM-SHA256 + **RSA-OAEP（jsbn，base64 按 214 字符分块）**
- ★ **华为把 SCRAM 的 HMAC 参数顺序写反了** —— 照 RFC 5802 写永远登不上，
  要反过来。见 `hwenc.py` 的注释
- `router.py` 封装登录与读写；`watch_ports.py` 实时看三个网口的协商速率

### Singtel Mesh（`singtel_mesh/`）

**登录算法**（从设备自带 `js/global.js` 逆出，用设备自己的 JS 在 Node 里逐字节验证过）：

```
token  = 登录页那张 1×1 GIF 的 data URI 的第 78 字符起（base64 解出来是个数字）
ArcMD5(x) = SHA512_hex(MD5_hex(x))
name   = ArcMD5(ArcMD5(用户名) + token)
pws    = ArcMD5(ArcMD5(密码)   + token)
```

坑：

- **必须带 `httoken` 字段**（= token），漏了永远 `loginpserr.htm`
- **必须带 Referer / User-Agent**，否则 302
- **token 是一次性的** —— 登录会消耗掉它，之后每个请求都要重新从页面取。
  ★ 这正是"写配置永远崩溃"的根因：拿已消耗的 token 打 `toplogy.cgi`，
  CGI 失败后服务端吐 `error`，客户端看到的是 `BadStatusLine('error')`
- `.exe` 端点全部 connection reset；能用的只有 `.cgi` 和 `/cgi/*.js`
- 重命名节点时 `device_mac` **不是网卡 MAC**，是**网卡 MAC 最后一字节 +1**；
  传错也返回 `ok` 但静默不生效

**真正能用的写接口**：

```
POST /cgi-bin/toplogy.cgi
  cmd=syncwificonfig    data=<17 段，用 "?$[+" 拼接>   → 返回 ok_wifi
  cmd=syncdevicename    data=<内部MAC>?$[+<新名>       → 返回 ok
  cmd=syncpasswdconfig2 data=<encode(新密码)>          → 返回 ok（但见下）
```

`encode(pwd)` = **每个字符 +97、空格分隔**。`change_pwd.htm` 里那段 packed JS 的
字典里有个 `wg7005d` 是**诱饵**，真正用的是 `key="a"`。

### ★ 管理密码为什么改不了（2026-10-14 查实）

**两条路径完全不同：**

| 路径 | 命令 | 实际效果 |
|---|---|---|
| 强制路径 `change_pwd.htm` | `syncpasswdconfig2`，`data=encode(新)` | **只清掉"必须改密码"闸门，根本不写密码** |
| 正常路径 `system_p.htm` | ① `POST setpwd.cgi`（`pws=ArcMD5(新)`/`chk=ArcMD5(旧)`）② `syncpasswdconfig`（`data=encode(旧)+"?"+encode(新)`） | **`setpwd.cgi` 才是真正写密码的那一步** |

**所以走强制路径改密码后，新旧密码都进不去** —— 密码停在一个半提交的坏状态。
浏览器里的表现也是"紫灯闪一下然后没下文"（浏览器流程最后那步提交到 `login.exe`，
而 `.exe` 在这台设备上是废的）。

**正确做法**：恢复出厂 → 用出厂密码登录（返回 `/change_pwd.htm` 也算成功，
**闸门只拦 `.htm` 页面，写接口照样能用**）→ 直接用 `final_apply.py` 写配置，
**完全不需要改密码**。

### ★ 登录锁

见 [`docs/singtel-mesh-login-lock.md`](docs/singtel-mesh-login-lock.md)。

一句话：**锁 = 配置里存在 `ARC_SYS_LoginBlocked` 这个键；失败满 10 次就写进 flash。
它跟时间无关，重启也清不掉，唯一可靠的清除办法是恢复出厂。**

**纪律**：绝不连续试密码。每次试之前先读登录页里的 `wait_secs`，不是 `0` 就绝对别发请求。

### ★ 冒充云端（`mqtt_spy/`）

设备通过 **MQTT over TLS** 连 `mqtt.wifi-analytics.singnet.com.sg:8883`。
用 DNS 劫持 + 自签证书就能冒充 —— **设备不校验证书**。

连上后设备会：

```
SUBSCRIBE devices/<MAC大写>/adornment        装饰/LED
SUBSCRIBE devices/<MAC大写>/desired_state    期望状态
SUBSCRIBE devices/<MAC大写>/direct           直接命令
PUBLISH   devices/data/shadow                zlib 压缩的身份上报
```

**★ 2026-10-17 更新**：云端 agent 找到了，就在 **Mesh Router 的 rootfs 里**
（`/usr/bin/embedur/erm_agent.tar.bz2`，**没有加密**）。它用的是**标准 MQTT + JSON**，
`devices/<MAC>/adornment`、`devices/<MAC>/desired_state`、`devices/<MAC>/direct`、
`devices/data/<ID>` 这些主题在二进制里逐字确认 —— 之前的抓包判断是对的。
详见 [`docs/singtel-cloud-agent.md`](docs/singtel-cloud-agent.md)。
**还没解的只剩“命令 JSON 的完整 schema”**，binary 已经到手，可以静态反汇编。

### ★ 固件与 bootloader

- [`docs/singtel-firmware-analysis.md`](docs/singtel-firmware-analysis.md) —— 加密地图、分区表、密码存储方式
- [`docs/uboot-web-recovery.md`](docs/uboot-web-recovery.md) —— ★ **u-boot 的 Web 恢复模式**（不鉴权，能写 bootloader）
- [`docs/spi-flash-dump-guide.md`](docs/spi-flash-dump-guide.md) —— ★ **SPI flash 读取指南**：三个解不开的目标，钥匙都在同一块 flash 里；含具体步骤、分区偏移、拿到 dump 后怎么用
- `kallsyms_extract.py` —— ★ **从裸内核解出 kallsyms 全符号表**：内核把符号名压缩存储，
  `strings` 只能捞到零星几个；这个工具解出全部（实测两台真机内核 40,349 / 17,483 个）
- `jffs2_extract.py` —— ★ **JFFS2 提取器（自动判端序）**：常规工具遇到「字段端序反了」
  或「CRC 约定不同」会直接失败，而这两件事看起来都像数据被加密了
- [`docs/arcadyan-cfe-nand-decode.md`](docs/arcadyan-cfe-nand-decode.md) —— ★
  **Singtel Mesh Router 固件完整解码**：小端 JFFS2 的破法、CFE 引导器的 Web 恢复模式、
  出厂板级字段表与默认值
- `flashdump.py` —— ★ **flash dump 自动分析**（配上一份指南用）：扫明文配置块/华为 keystring/AES 表/文件系统，按性价比顺序报出来

### ★★★ 配置备份解密

- [`docs/netgear-config-decrypt.md`](docs/netgear-config-decrypt.md) —— **NETGEAR 的 `.cfg` 完全可解**
  （XOR + `rand()`，**种子就写在文件头里**）。工具：`netgear_r7800/ng_cfgdec.py`
- [`docs/huawei-config-format.md`](docs/huawei-config-format.md) —— 华为 `aescrypt2` 的完整格式与算法
  （**密钥在设备上，不在文件里**）
- [`docs/arcadyan-singtel-config-format.md`](docs/arcadyan-singtel-config-format.md) —— ★
  **Arcadyan / Singtel 的配置与密码机制**：glbcfg **是明文**、密码派生规则
  （`s1ngt3l` + 序列号后 6 位，已实证）、extender rootfs 为什么解不开（附完整证据链）
- [`docs/singtel-cms-auth.md`](docs/singtel-cms-auth.md) —— ★★ **CMS 控制台认证**：
  `LOGIN_CFG`(0xC30) 三个账号槽位、`cmsDal_authenticate` 的 **明文 `strcmp`**、
  结果码 0x0A/2/1、与 web/SSH 密码三套独立
- [`docs/singtel-cms-dal-qdm.md`](docs/singtel-cms-dal-qdm.md) —— ★ **CMS DAL/QDM 函数地图**：
  `libcms_dal.so` 302 个函数（dalWan 41 / dalLan 36 / dalPMap 19 / dalSec 16 …）、
  `libcms_qdm.so` 180 个（qdmIpIntf 57 / qdmIntf 25 …）、TR-098/181 的 `_igd`/`_dev2` 双份实现
- [`docs/singtel-certificates.md`](docs/singtel-certificates.md) —— ★★ **证书体系**：
  ★ 固件自带 `www.singtel.com` 自签证书**及私钥**（httpd HTTPS）、
  OWL 的 `server.crt/server.key` + `ca.crt`、`create-*-cert.sh`（SHA-1 签发）、
  RootCA/WebServer/FTPS 动态证书
- [`docs/singtel-cms-and-consoled.md`](docs/singtel-cms-and-consoled.md) —— ★★ **CMS 数据模型与控制台**：
  `libcms_*` 五库、config flash 的 CRC/压缩头、`/bin/consoled`
  （`cmsCli_authenticate`/`cmsCli_run`，smd 失败会 drop to shell）、`cfgview`
- [`docs/singtel-wps-monitor.md`](docs/singtel-wps-monitor.md) —— ★★ **WPS 状态机**：
  EAPOL M1–M8 + UPnP WFAWLANConfig + 1905 三条入口、`wps_*` nvram 键、
  ★ `wps_aplockdown` PIN 爆破锁定（start/forever 计数）、状态码
- [`docs/singtel-midcore-protocol.md`](docs/singtel-midcore-protocol.md) —— ★★ **midcore 本地协议**：
  Unix socket `/tmp/arc-middle/core_trnx`、16 字节头（opcode@0x0A、length@0x0C）、
  opcode 1/2/3/5/6/7/10–15/20/21、0x284 字节记录、pcscfg_*/CFG_* API
- [`docs/singtel-web-cgi-map.md`](docs/singtel-web-cgi-map.md) —— ★ **web 端点与 CGI 地图**：
  `login/logout/setpwd/setpwd2/apply_abstract/get_info/get_topology_clients/json/owl_cmd/upload/mt`
  等端点、`get_*`/`set_*` 函数清单、认证辅助
- [`docs/singtel-arc-nvram-map.md`](docs/singtel-arc-nvram-map.md) —— ★★ **ARC 配置 ↔ nvram 映射**：
  `ARC_WLAN_*` → `wl0_*`/`wl1_*`/`fh_*`/`bh_*` 的键名对照、前缀/VAP 规则、
  `do_sync` 命令码、`nvram_set_brcm`/`wl -i` 链路
- [`docs/singtel-board-data.md`](docs/singtel-board-data.md) —— ★★ **板级数据（`arc_board`）**：
  完整键表与 NVRAM 名对照（`gui-pwd`/`arc_gui_pwd`、`wps-pin`/`wpsDevicePin`、
  `wifi-*-pwd`、`gpon-pwd`…）；一机一密的真正来源
- [`docs/singtel-config-key-universe.md`](docs/singtel-config-key-universe.md) —— ★★ **暴力枚举配置键**：
  2,155 个模板展开出 **38,193 个可能键**（`.glbcfg` 只有 2,361 个）；
  ★ 发现隐藏开关 `ARC_HTTPD_JSONAPI_Enable` 与 `json.cgi` / `/api/` 的
  `json_get_*`/`json_set_*` API
- [`docs/singtel-lan-and-wifi-insight.md`](docs/singtel-lan-and-wifi-insight.md) —— ★ **LAN 主机表与 WiFi Insight**：
  `pc_list_cli print/add/del`、`vis-cli -r/-b --chcapacity`、`/tmp/db/visdata.db`、
  RRM/STA/chanim 采集；均为本地数据（未见上云）
- [`docs/singtel-autofw.md`](docs/singtel-autofw.md) —— ★★ **自动固件升级**：
  `autofw` 的时间窗、`/GetFirmwareVersion` / `FirmwareDownloadResult` /
  `FirmwareUpgradeResult`、JSON 版本字段、下载后调 `fw_upgrade`、
  重启窗口与 `ARC_SYS_AUTOFW_*`；模板默认指向明文 HTTP 测试服务器
- [`docs/singtel-embedur-image-format.md`](docs/singtel-embedur-image-format.md) —— ★ **EmbedUR 镜像格式**：
  `image_manager` 的 6 参数、magic `0x112358D1`/`0x52237598`、32 字节 model 绑定、
  AES-CBC + MD5 + PKCS#7、0x100 签名块；与 `fw_upgrade` 是两条独立的升级链
- [`docs/singtel-owl-api.md`](docs/singtel-owl-api.md) —— ★★ **OWL 本地 HTTP API**：
  `/status/{DevInfo,MasterInfo,NetworkTime,stainfo,Wificonfig,tplg}`、
  `127.0.0.1:55761`、band steering 的 BTM/Legacy 决策、App 控制面、客户端证书
- [`docs/singtel-remaining-services.md`](docs/singtel-remaining-services.md) —— ★★ **剩余服务脚本**：
  DHCP/DNS、桥接/AP 模式、WAN/WLAN（`iwpriv` 细节、BSSID 规则、WPS）、
  L2TP/IPsec 钩子、VOIP/SIP、ALG、时区/DNS、恢复出厂、
  ★ `owl-tplg` 的 OWL 拓扑 HTTP 接口（`127.0.0.1:55761/status/tplg`）
- [`docs/singtel-config-engine.md`](docs/singtel-config-engine.md) —— ★★ **配置引擎**：
  `mng`/`mng_cli` 完整命令表（get/set/test/mget/mset/del/action/backup/
  restore/default/commit/tmp_*/dft_*/pget/stats）、`x`/`y` 索引与
  `%d`/`%02d` 格式、事务与落盘、默认值与升级迁移
- [`docs/singtel-leds-and-buttons.md`](docs/singtel-leds-and-buttons.md) —— ★ **LED 与按键**：
  GPIO 映射（低电平有效）、`arc_led` 命令、`arc_ledd`/`arc_gpiod` 守护；
  ★ GPIO32 按住 8 秒 = 恢复出厂，短按 = 重启
- [`docs/singtel-tr069.md`](docs/singtel-tr069.md) —— ★★ **TR-069 / CWMP**：
  Arcadyan CWMP 客户端、ACS `bs-hdm.singnet.com.sg`、默认 `singtel/singtel`、
  **45 秒一次 Inform**、30005 反向连接 + STUN、完整 RPC 列表、固件下载签名校验、
  ACS 能触发的 10 条 `tr69_*` 动作
- [`docs/singtel-wps-and-mesh-pairing.md`](docs/singtel-wps-and-mesh-pairing.md) —— ★ **WPS 与 mesh 配对**：
  前传 WPS 默认关、**回传 WPS 默认开且 PIN 出厂 12345670、PSK 12345678**；
  Broadcom WPS 状态码、板级数据覆盖、如何关闭回传 WPS
- [`docs/singtel-dbus-command-map.md`](docs/singtel-dbus-command-map.md) —— ★★ **dbus 命令字典**：
  35 个 agent、95 个唯一 `CMD_*`、`dbus-arca-cli` 用法与示例；
  ★ dbus policy 是 `context="default"` 全放行（无 uid/gid 限制）
- [`docs/singtel-boot-event-bus.md`](docs/singtel-boot-event-bus.md) —— ★★ **启动流程与事件总线**：
  `sysup` → dbus → 35 个 agent → `sys_boot` 的 50 步启动表；
  `/usr/share/msg/` 的 **210 个动作脚本**就是整机的“可执行动作字典”
- [`docs/singtel-firmware-update.md`](docs/singtel-firmware-update.md) —— ★★ **固件升级链路**：
  web → httpd → `/bin/fw_upgrade` → `libcms_util.so`；Broadcom tag/CRC/芯片 ID、
  SHA-256 + RSA 签名、A/B 分区与失败回退；`.trx` 的 `]Cot` 容器与尾部 64 KB 签名块
- [`docs/singtel-web-api-map.md`](docs/singtel-web-api-map.md) —— ★★ **web 字段 ↔ 配置键映射**：
  `ABS_MAP` 的数字 ID 其实是 `(模块<<16)|字段`，工具 `webmap.py` 从 `libarccfg.so`
  的 `mod_table`/`item_table` 直接翻译；实测 **414 条映射 / 332 个 ARC 键**
  （web 只覆盖 2361 个字段中的 332 个，其余是后台开关）
- [`docs/singtel-network-internals.md`](docs/singtel-network-internals.md) —— ★★ **网络面逐层解码**：
  IPv4/IPv6 防火墙（完整 iptables 规则、DoS/访问控制/`xt_webstr`）、
  QoS（HFSC/HTB + ICMP 自动测速）、VLAN/假 `eth0.0`、WBD mesh、IPv6（6RD/NAT64）、
  USB `chmod a+rwx`、LTE AT 命令、厂商自定义内核模块
- [`docs/singtel-cloud-agent.md`](docs/singtel-cloud-agent.md) —— ★★ **EmbedUR 云管理代理**：
  固件里默认开启的第三方代理（`ARC_3rd_EmbedUR_Enable=1`），MQTT 主题、能力面、
  自动重启策略、固件升级链路；★ 还挖出**本地 App 配网协议（UDP 9995 + JSON）**
  和**家长控制的 DNS 关键字拦截**；★ 固件里带着**与生产 broker 证书配对的私钥**
- [`docs/config-recovery.md`](docs/config-recovery.md) —— ★★ **配置恢复包**：
  四层配置结构（rootfs 出厂包 / tmpfs / `pricfg` 分区 / `data` JFFS2）、
  **web 备份 `Settings.CFG` 的离线解密**（`aes-256-cbc` + 固件里写死的口令，
  **必须 `-md md5`**）、以及从 rootfs / flash dump 里恢复配置的完整流程。
  工具：`cfgpack.py`

**三种设计的安全强度依次递增**：NETGEAR 把种子写在文件头里（所以能解）→
华为把密钥放设备上（一机一密）→ Arcadyan 把密钥放 bootloader 里（最靠下，最难拿）。

`cfgpack.py` 是 **Arcadyan/Singtel 配置恢复包**：分析 rootfs、解析 `glbcfg` 字段、
**离线解密/生成 web 备份 `Settings.CFG`**、从 flash dump 里 carve 配置 tar.gz。
`webmap.py` 把 web 界面的 `ABS_MAP` 数字 ID 翻译成真正的 `ARC_*` 配置键
（直接读 `libarccfg.so` 的模块表/字段表）。
`cfgkeys.py` 把字段表按索引上限全部展开，暴力枚举出 **38,193 个可能配置键**
（并找出 `.glbcfg` 里没有的隐藏开关）。

统一工具 `routercfg.py` **五种格式**都认：NETGEAR 配置 / **NETGEAR 官方固件** /
华为配置 / Arcadyan .trx / Arcadyan glbcfg（含华为的 **HMAC 密钥验证器**）；
`arckey.c` 是 Arcadyan squashfs 的 **AES 密钥搜索器**（已锁定靶子与判据，dump 到手一条命令）；
`hwkey.c` 是华为 aescrypt2 的**高速密钥破解器/验证器**（C + 多线程，约 2400 条/秒，判据是 256 位 HMAC，零误判）。

---

## 脚本速查

```bash
# Singtel Mesh
python3 singtel_mesh/sg.py status              # 设备状态
python3 singtel_mesh/snapshot.py now.json      # 快照 100 个字段
python3 singtel_mesh/recover.py --ch --name    # 恢复信道 + 节点名
python3 singtel_mesh/final_apply.py            # ★ 恢复出厂后一键重配（最常用）
python3 singtel_mesh/login_once.py <密码>      # 安全登录：先确认 wait_secs=0 再登

# 华为主路由
python3 hw_q2s/watch_ports.py                  # 实时看三个网口速率

# 冒充云端（需要 sudo 拿 53/123/443）
sudo python3 mqtt_spy/broker_tls.py            # 1883 明文 + 8883 TLS
```

---

## 目录

```
docs/           逆向笔记（登录锁 / 固件 / JFFS2 / 三种配置格式 / 配置恢复 / SPI dump）
singtel_mesh/   Arcadyan mesh 工具集（★ 主要在这里）
hw_q2s/         华为 Q2S REST API 客户端
mqtt_spy/       假云端 MQTT broker（含 TLS）
acs/            假 TR-069 ACS + 极简 NTP 服务器
netgear_r7800/  NETGEAR SOAP API 客户端
```

**固件本体不进 git**（`.gitignore` 已排除 `*.trx`/`*.bin`/`*.sqsh` 等）。
