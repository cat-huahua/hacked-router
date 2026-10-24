# EmbedUR JSON 分派：radio 配置、members 与 enhanced steering

本轮只静态读取 `rrm_bcm_arm`，未运行目标、访问路由器或发送 MQTT/UDP。
样本 SHA-256：`05976d3c211fbf0107aa4f858bb16b5e7ce22d24441ab46c70a5374071de1325`。
与 [cloud agent 总览](singtel-cloud-agent.md) 配套，本篇补充字段的数据流并收窄旧文中
“其它 desired_state 字段”的表述。这里记录协议字段名，不记录任何真实凭据、SSID、MAC 或节点名。

## 1. 已解：这些字段并非都受 desired_state 条件约束

入口是日志字符串标识的 `handle_json_socket`，VA `0x4e218`。
代码先检查命令形态，再进入 `type=accesspoint` / `statetype=desired_state` 的位置配置分支：

| 入口条件（按先后顺序） | 实际分支 | 证据 VA / file offset |
|---|---|---|
| `method`、`session_id`、`members` 三者指针均存在 | 调用 `0x9f6b4`（parental controls），跳过后续分派 | `0x4e7bc–0x4e818` / `0x3e7bc–0x3e818` |
| `method` 与 `session_id` 均存在，且 `radio_24` 或 `radio_5` 至少一个存在 | 调用 radio handler `0x7c478`，随后释放 JSON 并返回 | `0x4e81c–0x4e864` / `0x3e81c–0x3e864` |
| 后续位置条件 | `accesspoint/config/location` 写入 | `0x4e920–0x4e9dc` / `0x3e920–0x3e9dc` |
| `gateway_topic` 存在 | 更新内存主题，特定状态调用 `0x59e64`，然后返回 | `0x4e9f0–0x4ea70` / `0x3e9f0–0x3ea70` |
| `enh_blacklist_config` 存在 | blacklist 分支，处理完后才继续检查 steer | `0x4ea74–0x4ef14` / `0x3ea74–0x3ef14` |
| `enh_steer_config` 存在 | steer 数组读取/日志分支 | `0x4ef18–0x4f440` / `0x3ef18–0x3f440` |

**静态事实：** radio/member 检查发生在 `type` / `statetype` 比较之前，不能仅凭字段
与 `desired_state` 出现在同一函数，就把它们全部归为 desired_state 配置落盘字段。
这里的“存在”是 `json_object_get` 返回非 NULL；并不等价于完成严格 JSON schema 校验。
本篇也不由此推断 MQTT 或 UDP 网络入口的认证状态。

## 2. 已解：radio JSON → 0xe8-byte 记录 → Arcadyan 配置

`0x7c478` 再读取 `method` / `session_id` / 两个 radio 字段。只明确比较
`get`、`GET`、`set`、`SET`；其它大小写组合不在这组比较中。
SET 对存在的 band 调用 `0x7c07c(array, buffer)`，再调用
`0x975d0(band, 4, buffer)`；`radio_24` 的 band=0，`radio_5` 的 band=1。

### 2.1 逐字段记录布局

`0x7c07c` 先验证输入非 NULL 且 JSON 类型为 array（首 word=1），逐个 array item
读取字段。以传入 buffer 为基址，item i 的 record 起点为 `buffer + i*0xe8`：

| 字段 | 读取方式 | record 相对偏移 | 缺字段时行为 | 读取/写入 VA（file offset=VA−0x10000） |
|---|---|---|---|---|
| `wlan` | `json_integer_value` | `+0x04` | 使用数组下标 i | `0x7c1f0–0x7c20c` |
| `encryption` | `json_integer_value` | `+0x08` | 0 | `0x7c124–0x7c140`, `0x7c1ac` |
| `ssid` | `json_string_value` → `strcpy` | `+0x0c` | 首 byte 清零 | `0x7c0c0–0x7c0e4` |
| `key` | `json_string_value` → `strcpy` | `+0x2d` | 首 byte 清零 | `0x7c0e8–0x7c10c` |
| `wep` | 最多取 4 个字符串 | `+0x6d + j*0x1b` | 未显示统一清零全部槽位 | `0x7c110–0x7c1a8` |
| `hidden` | `json_integer_value` | `+0xdc` | 0 | `0x7c1b0–0x7c1cc` |
| `enable` | `json_integer_value` | `+0xe0` | 0 | `0x7c1d0–0x7c1ec` |

record `+0x00` 与 `+0x04` 后续会被平台 writer 写入 band 和循环下标。
记录步长是 `0xe8`，来自 `0x7c214`；它不是 JSON 长度。

### 2.2 平台 writer 实际消费的字段

**静态事实：** `0x975d0` 并未应用 parser 的所有字段。它只取 `+0x2d`、`+0x0c`，
分别拼接 WPA passphrase 和 ESSID 的 `mngcli set`，然后把每槽的 Enable 固定写为 1。
以下仅为固件内格式字符串，不包含实际配置值：

```text
mngcli set ARC_WLAN_%s_SSID_%d_WPA_Passphrase=%s
mngcli set ARC_WLAN_%s_SSID_%d_ESSID=%s
mngcli set ARC_WLAN_%s_SSID_%d_Enable=%d
```

band 名来自一个 10-byte 字符串表（`24G\0\0` / `5G\0\0\0`），按 `band*5` 选择。
调用点传入数量恒为 4，writer 循环在 i>=4 时结束。因此是 band 内槽位 0–3，
并非使用 JSON `wlan` 字段选择槽位；parser 读到的 `wlan` 被 writer 的 i 覆盖。
`encryption`、`wep`、`hidden`、传入 `enable` 在这段 writer 中没有消费。

两 band 处理完后，handler 调用 `sleep(1)`，再进 `0x976b4`：

```text
mngcli commit
mngcli action ui_wireless
```

这补齐了 JSON → Arcadyan 配置键 → commit → wireless action 的闭环。
但 SET 分支在执行 writer **之前**已构造 `Set Successful`，writer 的返回值也没有用于
改写该结果；不能把这种响应当作实际命令成功或无线配置已生效的证明。

**未解/限制：** handler 固定传 4，parser 却按实际 array 大小遍历；本轮未证明少于
4 项的 buffer 其它槽被初始化，也未证明 parser 对大于 4 项的全局上限检查。没有执行
异常长度测试。本篇不把此静态观察升级为已验证漏洞。

### 2.3 GET 的返回范围

`0x7c270` 对 band 0/1 各调用 `0x97370` 获取配置，构造 `method="GET"`、
`session_id`、`index`，以及两个各包含一个对象的 `radio_24` / `radio_5` array。
每个对象序列化 `ssid`、`key`、`encryption`，不是把 parser 全部字段原样返回。
GET handler 随后经 `0x9f648` / `0x9f674` 转换并把结果放入响应 message；这两个函数
的完整编码语义不在本轮解码范围。未读取或导出任何实际 key 值。

## 3. 已解：enh_steer_config 在此入口只读取和打印

顶层要求存在 `mac`，否则进入释放 JSON/返回路径。`enh_steer_config` 被当作 array，
循环每项读取以下五个字段：

| 字段 | 类型读取 | VA / file offset |
|---|---|---|
| `ap` | string，保存供自身标识比较 | `0x4f210–0x4f230` / `0x3f210–0x3f230` |
| `ssid` | string，仅用于可选日志 | `0x4f25c–0x4f2a8` / `0x3f25c–0x3f2a8` |
| `bssid` | string，仅用于可选日志 | `0x4f2ac–0x4f2f8` / `0x3f2ac–0x3f2f8` |
| `state` | integer，仅用于可选日志 | `0x4f2fc–0x4f348` / `0x3f2fc–0x3f348` |
| `timer` | integer，仅用于可选日志 | `0x4f34c–0x4f398` / `0x3f34c–0x3f398` |

`0x4f39c–0x4f408` 将 `ap` 与全局结构 `0x23f9e0 + 0x814` 所指字符串 `strcmp`。
相等和不等分支都只可能调用日志函数 `0x850e8`，然后进入下一项。原文日志分别是
`My ID ignore \n`、`NOT My DONT ID ignore \n`。循环后在 `0x4f40c` 释放 JSON，返回。

**有边界的静态结论：** 这条入口的 steer 数组分支没有通向配置 writer、steering
执行器或驱动调用；不能继续把它描述成已确认可执行的 steering 命令。这个结论仅
覆盖这段控制流，不排除固件其它函数存在同名配置生产/消费逻辑。

## 4. 部分解：enh_blacklist_config 有实际动作，与 steer 不同

blacklist 同样要求顶层 `mac`，每项读取 `ap`、`ssid`、`bssid`、`state`、`timer`。
`ap` 必须与同一自身标识匹配才能进入动作（`0x4edd4–0x4ede8`）。顶层 `mac`
经 `0x19704` 转成 6-byte buffer（`0x4edc8–0x4edd0`）。

- `state==0`：调用 `0x5e83c(mac,1,-1)` 取得记录，然后写 `+0xc=0`、
  `+0x2c=0`、`+0x28=时间读取结果`（`0x4edec–0x4ee60`）。日志原文包含
  `enhanced steer SPECIAL HANDLE`。尚未完整恢复这三个内部字段名。
- `state!=0`：拒绝全零 MAC；随后对 band 1、band 0 各调用一次
  `0x5ffcc(band, mac_bytes, ssid, 0)`（`0x4ee64–0x4ef0c`）。
  被调函数日志标识为 `load_balancer_block_mac_address`，内部确有
  `wl -i %s macmode`、`wl -i %s macmode %d`、`wl -i %s mac`、
  `wl -i %s mac %02x:%02x:%02x:%02x:%02x:%02x` 和 deauthenticate 命令格式。

`timer` 在这段 JSON 分支只用于日志，未见作为参数传给上述动作；不能据其名称断言
以秒计时或此字段控制封禁时长。`bssid` 在上述动作点也只用于日志，SSID 才传入
`0x5ffcc` 做接口匹配。具体 macmode 转换和记录超时状态机仍未完整解码。

## 5. 部分解：members 属于 parental controls 命令

`0x9f6b4` 的日志函数名是 `handle_parental_controls`，源文件字符串是
`rrm_interface/parental_controls.c`。它显式比较 `add/ADD`、`delete/DELETE`、
`get/GET`（`0x9f778–0x9f7f0`），后续还有 set 分支。配置文件是
`/data/embedur/parental_controls.json`。

本轮定位到逐 member 的嵌套路径：

```text
members[]
  id
  clients
  policies
    time_based[]
      name
      start
      end
      weekdays
```

证据为 `0x9fbec–0x9fca4` 的 `json_array_get` / `json_object_get` 数据流。
注意 `clients` 是从 member 对象读取，而 `name/start/end/weekdays` 从 time_based item
读取。更深的规则 CRUD、时间编码、clients 形态及持久化转换留待后续，本篇不由
字符串反推完整 schema。

## 6. 证据索引与复核方法

本样本 ELF 的第一个 LOAD：file offset `0` → VA `0x10000`，因此本篇所有代码及
rodata 地址的 file offset 都是 VA−`0x10000`。`readelf -lW` 可核对；以下可用
`r2 -q -e scr.color=0 -c 's <VA>; af; pdf' <sample>` 离线复核，不需要目标运行。

| 对象/字符串原文 | VA | file offset | 支持的结论 |
|---|---:|---:|---|
| `handle_json_socket` | `0x1bd657` | `0x1ad657` | 入口日志身份，入口代码 `0x4e218` |
| `members` | `0x1cb6ac` | `0x1bb6ac` | 第一优先命令分派 |
| `radio_24` / `radio_5` | `0x1c89e7` / `0x1c89f2` | `0x1b89e7` / `0x1b89f2` | 两band字段 |
| radio handler / parser | `0x7c478` / `0x7c07c` | `0x6c478` / `0x6c07c` | method分派、record映射 |
| platform writer / commit | `0x975d0` / `0x976b4` | `0x875d0` / `0x876b4` | 配置写入、提交、action |
| `ssid` / `key` | `0x1de5ce` / `0x1c8eb9` | `0x1ce5ce` / `0x1b8eb9` | radio parser字段名 |
| `wep` / `encryption` | `0x1d9986` / `0x1c8e5a` | `0x1c9986` / `0x1b8e5a` | radio parser字段名 |
| `hidden` / `enable` / `wlan` | `0x1c8e65` / `0x1d0155` / `0x1bf29c` | `0x1b8e65` / `0x1c0155` / `0x1af29c` | radio parser字段名 |
| 三条 mngcli set 格式（见正文） | `0x1e00f0`, `0x1e0121`, `0x1e0149` | `0x1d00f0`, `0x1d0121`, `0x1d0149` | 实际写入键 |
| `mngcli commit` / `mngcli action ui_wireless` | `0x1e0172` / `0x1e0180` | `0x1d0172` / `0x1d0180` | 提交闭环 |
| `enh_steer_config` / `enh_blacklist_config` | `0x1cb6c2` / `0x1cb6d3` | `0x1bb6c2` / `0x1bb6d3` | 两个独立分支 |
| `ap` / `bssid` / `state` / `timer` | `0x1be110`, `0x1be0f7`, `0x1e7c35`, `0x1c0598` | `0x1ae110`, `0x1ae0f7`, `0x1d7c35`, `0x1b0598` | steering逐项字段 |
| `My ID ignore \n` / `NOT My DONT ID ignore \n` | `0x1cb914` / `0x1cb923` | `0x1bb914` / `0x1bb923` | steer分支只打印的路径 |
| blacklist执行函数 | `0x5ffcc` | `0x4ffcc` | 下游wl命令构造 |
| `handle_parental_controls` | `0x1e0305` | `0x1d0305` | `0x9f6b4`身份 |
| `/data/embedur/parental_controls.json` | `0x1e11e9` | `0x1d11e9` | members持久化文件 |
| `policies` / `time_based` / `weekdays` | `0x1d9965`, `0x1d995a`, `0x1d9951` | `0x1c9965`, `0x1c995a`, `0x1c9951` | member规则层级 |

## 7. 尚未解决

- 两band GET底层读取 `0x97370` 的全部配置来源、响应转换器的编码格式。
- members CRUD的全部schema、时间表示、所有错误响应及落盘实现。
- enhanced blacklist内部记录的完整字段名、超时回收、macmode各值语义。
- 其它入口是否消费同名 `enh_steer_config`，以及 `private/eac/client_probe_info` 全流程。
- MQTT `direct` / `image` 的完整payload；本轮不声称已达到 decode all。
