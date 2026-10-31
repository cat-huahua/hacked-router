# Singtel Mesh Router 的配置引擎：`mng` / `mng_cli` / `libarccfg`

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/sbin/mng_cli`、`/usr/sbin/mng`、`/usr/lib/libmng.so`、
> `/usr/lib/libarccfg.so`、`/usr/share/config/etc/config/.glbcfg`
> 一句话：**所有配置读写最终都走 `mng`（midcore）→ `libarccfg`；
> `mng_cli` 只是它的命令行前端。**

---

## 1. 组件关系

```
web / TR-069 / dbus / shell
        │
        ├─ mng_cli get/set/action/...        ← 命令行前端
        │      └─ 通过 /tmp/mng_core 与 midcore 通信
        │
        ├─ mng_action（libmng）
        │      └─ 发到 arca.dbus.mng，日志 /tmp/arca_action.log
        │
        ▼
   midcore / mng（配置守护）
        │
        ├─ libarccfg：字段表、索引、默认值、事务
        └─ .glbcfg / pricfg 分区
```

`mngcli` 只是 `mng_cli` 的符号链接：

```
/usr/sbin/mngcli -> /usr/sbin/mng_cli
```

脚本里两种拼写都有人用（`mng_cli` / `mngcli`）。

---

## 2. `mng_cli` 完整命令表

二进制里的 usage 原文：

```
Usage:
    mng_cli get <name>[@<section>]
    mng_cli set <name>[@<section>]=<value>
    mng_cli test <name>
    mng_cli mget <name_1> <name_2> .. <name_n>
    mng_cli mset <name>=<value> <name>=<value> .. <name>=<value>
    mng_cli del <name>
    mng_cli action <name>[=<param>]
    mng_cli backup <to_file>
    mng_cli restore <from_file>
    mng_cli default
    mng_cli commit
    mng_cli tmp_get <name>
    mng_cli tmp_set <name>=<value>
    mng_cli dft_get <name_1> <name_2> .. <name_n>
    mng_cli mng_status
    mng_cli pget <name>
    mng_cli dft_pget <name>
    mng_cli stats
```

| 命令 | 作用 |
|---|---|
| `get` | 读当前值 |
| `set` | 写当前值（内存/事务，未 commit） |
| `test` | 校验值是否合法 |
| `mget` / `mset` | 批量读/写 |
| `del` | 删除字段（回到“未设置”） |
| `action` | 执行 `/usr/share/msg/<name>` 动作链 |
| `backup` / `restore` | 导出/导入配置 |
| `default` | 恢复默认值 |
| `commit` | **落盘**（写 `pricfg` 分区） |
| `tmp_get` / `tmp_set` | 临时值（不落盘，供启动迁移用） |
| `dft_get` | 读出厂默认值 |
| `mng_status` | 守护状态 |
| `pget` / `dft_pget` | 按前缀批量取（prefix get） |
| `stats` | 统计 |

错误串里能看到它依赖 `midcore`：

```
Could not start a transaction to arc middle, possible reasons are:
    - Insufficient memory
    - midcore not initialized yet
    - Insufficient socket resource
```

### 2.1 `arc_cfg_cli`：数字 ID 版

`/usr/sbin/arc_cfg_cli` 直接用 **`(模块<<16)|字段`** 的数字 ID 操作配置：

```
abscfg showID [cfgID]                 # 列出/显示 cfgID
abscfg get cfgID [index1] [index2]
abscfg set cfgID [index1] [index2] <value>
abscfg unset cfgID [<idx1 min> <idx1 max>] [<idx2 min> <idx2 max>]
abscfg get_idx_limit cfgID
abscfg testapi                        # 跑 arc_cfg_* 自测
```

例子（`ARC_LAN_x_IP4_Addr` 的 ID 是 `0x20004`）：

```sh
abscfg get 0x20004 0        # 读 ARC_LAN_0_IP4_Addr
abscfg set 0x20004 0 192.168.3.2
abscfg get_idx_limit 0x20004
```

它还带一套 `Test API: arc_cfg_get/set/match/cmp ...` 自测，
以及 `showID`（配合 `webmap.py` 的数字 ID 表查名字）。

---

## 3. 键的命名与索引

### 3.1 基本形式

```
ARC_<模块>_<字段>
```

例如：

```
ARC_SYS_Password
ARC_WAN_0_IP4_Addr
ARC_WLAN_24G_SSID_0_ESSID
ARC_WLAN_24G_SSID_0_WPA_Passphrase
```

### 3.2 `@section`

`mng_cli get <name>[@<section>]` 的 `@section` 用来区分同名配置所在的“段”
（不同项目/命名空间）。普通脚本里基本不用；看到 `@` 时按字面理解即可。

### 3.3 索引占位符 `x` / `y`

`libarccfg` 的字段表里，带索引的字段写成：

```
名字（给人看）                格式串（真正拼键用）               idx1 上限  idx2 上限
ARC_WAN_x_Enable              ARC_WAN_%d_Enable                  4          0
ARC_WAN_xy_Enable             ARC_WAN_%d%02d_Enable              4          4
ARC_SYS_SCHEDULER_x_Enable    ARC_SYS_SCHEDULER_%d_Enable        0x20       0
```

规则：

- `x` → 第一个索引（index1）
- `y` → 第二个索引（index2）
- 格式串里的 `%d` / `%02d` 决定补零方式
- 字段表项 32 字节：`[名字指针][格式串指针][idx1 上限][0][idx2 上限][0][0][0]`

`_combine_general_cfg_name()` 就是做这个替换：

```c
sprintf(out, entry->fmt, idx1, idx2);   // 两个索引都有时
sprintf(out, entry->fmt, idx1);         // 只有 idx1 时
```

### 3.4 数字 ID（web 层用）

web 的 `ABS_MAP` 用数字 ID，编码是：

```
id = (模块号 << 16) | 字段序号
0x6000F → ARC_SYS 第 15 项 → ARC_SYS_SerialNum
0x20003 → ARC_LAN 第 3 项  → ARC_LAN_x_MACaddr
```

模块顺序（`mod_table`）：

```
0 TEST  1 WAN  2 LAN  3 WLAN  4 VO  5 UI  6 SYS  7 TR64  8 TR69
9 BOOTSTRAP 10 FIREWALL 11 QOS 12 NAT 13 USB 14 UPNP 15 PROJ
16 ROUTE 17 IP6 18 DDNS 19 IGMP 20 VPN 21 OMCI 22 OWL
```

工具 `webmap.py` 可直接把 web 字段翻译成 `ARC_*` 键。

---

## 4. 事务与落盘

`mng_cli` 字符串里能看到：

```
mapi_start_transc / mapi_end_transc
mapi_ccfg_set_multiple / mapi_ccfg_get_multiple
mapi_ccfg_commit / mapi_ccfg_backup / mapi_ccfg_restore
mapi_ccfg_default / mapi_ccfg_unset / mapi_ccfg_reset_dft
```

流程：

```
set/tmp_set  → 内存/事务
commit       → 写 .glbcfg → arccfg commit → pricfg 分区（.config.tgz）
```

**不 commit 的修改在重启后会丢**（除非走 `tmp_set`，它本来就是临时的）。

`arccfg commit` 负责真正的 flash 写入；`arccfg checkout` 负责开机解出。
详见 [config-recovery.md](config-recovery.md)。

---

## 5. 默认值与升级迁移

`/etc/config/` 下有三个特殊文件：

| 文件 | 作用 |
|---|---|
| `glbcfg.dft` | **出厂默认值**（2361 个字段） |
| `glbcfg.fix` | 升级时要**保留**的字段清单 |
| `glbcfg.sme` | SME / 非 SME 固件切换时要**重置**的字段 |

`arc_glbcfg` 启动时：

1. 用 `mng_cli backup` 导出当前配置；
2. 和 `glbcfg.dft` 做 diff，找出**新增字段**并 `set` 进去；
3. 把 `glbcfg.fix` 里的旧值恢复；
4. `mng_cli commit`。

所以升级不会丢配置，但会补齐新版本新增的字段。

---

## 6. 动作（`mng_cli action`）

```
mng_cli action <name>[=<param>]
```

它会执行 `/usr/share/msg/<name>` 里的动作脚本，例如：

```sh
mng_cli action sys_boot
mng_cli action reboot
mng_cli action ui_wireless
```

`libmng` 的 `mng_action()` 会：

```
发到 arca.dbus.mng: (Action: <name> Param: {<param>})
日志写 /tmp/arca_action.log
```

动作链的完整字典见 [singtel-boot-event-bus.md](singtel-boot-event-bus.md)
（210 个 `msg` 文件）。

---

## 7. 常用示例

```sh
# 读
mng_cli get ARC_SYS_Password
mng_cli get ARC_WLAN_24G_SSID_0_ESSID

# 写 + 落盘
mng_cli set ARC_WLAN_24G_SSID_0_ESSID="MyWiFi"
mng_cli commit

# 批量
mng_cli mget ARC_SYS_Password ARC_TR69_URL
mng_cli mset ARC_SYS_LoginEnable=1 ARC_SYS_HTTP_Enable=1

# 默认值 / 删除
mng_cli dft_get ARC_SYS_Password
mng_cli del ARC_WLAN_24G_SSID_0_WPA_Passphrase
mng_cli commit

# 备份 / 恢复（纯文本 .glbcfg）
mng_cli backup /tmp/cfg.bak
mng_cli restore /tmp/cfg.bak

# 临时值（不落盘）
mng_cli tmp_set ARC_SYS_Test=1
mng_cli tmp_get ARC_SYS_Test

# 触发动作
mng_cli action reboot
```

---

## 8. 风险

1. **`default` / `del` 是破坏性的**：`mng_cli default` 会把配置恢复出厂；
   `del` 加 `commit` 会让字段回到“未设置”，服务可能起不来。
2. **`commit` 才落盘**：只 `set` 不 `commit`，重启即丢；反过来，
   `commit` 写 flash，频繁写会磨损 `pricfg`。
3. **软件重启和冷断电须区分**：已记录的reboot消息脚本包含commit，
   见[事件总线](singtel-boot-event-bus.md)；不能据此推断其它路径也提交，
   或用软件重启验证断电持久性。
4. **`@section` 写错会改到别的命名空间**，脚本里很少用，别乱加。
5. **`mng` 挂了整机不可配置**；`pslist.conf` 会拉起它（`mng` 异常退出→重启）。

---

## 9. 证据索引

| 内容 | 位置 |
|---|---|
| CLI 命令表 | `/usr/sbin/mng_cli` 的 usage 字符串 |
| 前端符号 | `mapi_ccfg_*` / `mng_action` / `mapi_start_transc` |
| 动作日志 | `libmng`：`/tmp/arca_action.log`、`arca.dbus.mng` |
| 字段表 | `libarccfg.so` 的 `mod_table` / `arc_*_cfg_item_table` |
| 名称组合 | `_combine_general_cfg_name` @ `0x134E8` |
| 默认/迁移 | `glbcfg.dft` / `glbcfg.fix` / `glbcfg.sme`、`arc_glbcfg` |
| 落盘 | `arccfg commit` / `checkout`（见 config-recovery.md） |
