# `midcore` 的本地配置协议

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/usr/sbin/midcore`（14.5 KB，stripped）、`mng_cli`、`libmng`
> 一句话：**`midcore` 是一个 Unix socket 服务，`mng_cli`/`mng` 用
> 16 字节头 + 定长记录跟它说话。**

---

## 1. 进程与 socket

`main`（`0x112AC`）：

```c
socket(AF_UNIX, SOCK_STREAM, 0)
bind(sock, "/tmp/arc-middle/core_trnx")
listen(sock, 100)
touch("/tmp/.arca-midcore.ok")
select_loop(...)
```

- 地址：**`/tmp/arc-middle/core_trnx`**
- 还有一个 `/tmp/arc-middle/clientwait`（客户端等待/同步用）
- 就绪标记：`/tmp/.arca-midcore.ok`
- 最多同时服务 **0x3FE（1022）** 个客户端（`fd_set` 大小）

---

## 2. 报文格式

首次 `recv` 读 **0x40（64）字节**，然后：

```c
length = *(uint32_t *)(buf + 0x0C);   // 总长度
if (length < 16) → "illegal message: length[%d], expect [%d]"
realloc(buf, length + 10);            // +10 = 尾部余量
recv 剩余字节
handle_msg(buf)
```

### 16 字节头（偏移）

| 偏移 | 类型 | 含义 |
|---:|---|---|
| `0x00` | u32 | 保留/标志 |
| `0x04` | u32 | 请求 ID / 客户端序号（回包原样带回） |
| `0x08` | u16 | 保留 |
| `0x0A` | u16 | **opcode**（0..0x15） |
| `0x0C` | u32 | **总长度**（含 16 字节头） |
| `0x10` | — | payload 开始 |

回包复用同一个 buffer：

```
*(uint16_t *)(buf + 0x0A) = 状态码;
*(uint32_t *)(buf + 0x0C) = 长度;
send(buf, 长度);
```

发送时按 **0x4000（16 KB）** 分块。

---

## 3. 操作码（从 switch 反汇编）

`handle_msg` 用 `ldrh op,[buf+0x0A]` 做 22 路 switch（0..0x15）。
能确认的：

| opcode | 动作 | 底层调用 |
|---:|---|---|
| 0 | 成功/空操作（回显请求 ID） | 设置回包长度后返回 |
| 1 | 读配置 | `pcscfg_get`（`MID_MNG_Get: %s Fail`） |
| 2 | 测试/校验 | `pcscfg_test` |
| 3 | 删除 | `pcscfg_del` |
| 4 / 8 / 9 | **未知请求** | 日志 `MNG_Unknown request: code %d name %s`，状态置 `0xFFFF0FFF` |
| 5 | 备份 | `pcscfg_backup` |
| 6 | 恢复 | `pcscfg_restore` + `pcscfg_commit` |
| 7 | 提交 | `pcscfg_commit`（日志 `%s call commit`） |
| 10 / 11 | 读写（带请求 ID） | 分配结果对象 + 记录 |
| 12 | 批量读 | 按 **0x284** 字节/记录遍历 |
| 13 | 批量写 | 按 0x284 字节/记录遍历 |
| 14 | 批量删除/标记 | 按 0x284 字节/记录遍历 |
| 15 | `default` | 比较 payload 里的 `"default"` → `pcscfg_restore("/etc/config/glbcfg.dft")` + commit + `arccfg default` |
| 16 | 保存/同步 | `CFG_SearchCfgElmCache` + `CFG_CalConfigSpace` + `CFG_SaveConfigure` |
| 17 | 统计/转储 | `malloc_stats` + `CFG_CalAllParameters` + `CFG_ShowCacheHit`，写文件 |
| 18 | 配置复制/导出 | `0x12A54` + `strcpy` |
| 19 | 简单复制 | （无外部调用） |
| 20 | 测试 | `pcscfg_test` |
| 21 | 恢复默认 | `pcscfg_restore("/etc/config/glbcfg.dft")` + `arccfg default` |

> 跳转表在 `0x1271C`（22 个绝对地址）；上面每一项都对应表里的目标地址。

### 记录大小 0x284 = 644 字节

批量操作按 `0x284` 字节一条记录遍历：

```c
count = (length - 0x10) / 0x284;
for (i = 0; i < count; i++) { ... p += 0x284; }
```

每条记录里：

```
+0x00 .. +0x27F   配置记录
+0x280            u32 标志/状态（case 12/14 会置 1）
```

---

## 4. 涉及的配置 API

`midcore` 导入的符号（没有源码，但名字很直白）：

```
pcscfg_open / pcscfg_get / pcscfg_set / pcscfg_del
pcscfg_test / pcscfg_commit / pcscfg_backup / pcscfg_restore
pcscfg_sizeget
CFG_GetConfigure / CFG_SaveConfigure / CFG_SaveAllConfigure
CFG_SearchCfgElm / CFG_SearchCfgElmCache / CFG_ConstructCFGFullName
CFG_CalConfigSpace / CFG_CalAllConfigSpace / CFG_SetAlias
CFG_DeleteCfgElm / CFG_ShowCacheHit / CFG_CalAllParameters
```

文件：

```
/etc/config/.glbcfg        运行时配置
/etc/config/glbcfg.dft     默认值
/tmp/tmpcfg.txt            临时配置
/tmp/cfgaccess.txt         访问日志
/tmp/setlog.txt            set 日志
```

---

## 5. 和 `mng_cli` 的关系

```
mng_cli get/set/commit/...
   → libmng（mng_action / send_msg）
   → /tmp/arc-middle/core_trnx
   → midcore
   → pcscfg_* / CFG_*
```

`mng`（另一个进程）也走同一个 socket，负责把 dbus/动作转成配置操作。

---

## 6. 安全观察

1. **没有 TLS/鉴权**：Unix socket，本地任意进程可连（权限取决于
   `/tmp/arc-middle/` 和 socket 的 umask）。
2. **16 字节头 + 长度字段**：长度校验只要求 `>=16`，然后 `realloc(len+10)`；
   如果 `len` 很大，可能造成大内存分配（本地攻击面）。
3. **批量记录 0x284**：如果 `(len-0x10)` 不是 0x284 的整数倍，最后一条可能越界读；
   代码用 magic 除法取整，未看到余数校验。
4. **`default` opcode 会恢复出厂**（`glbcfg.dft`）并 `arccfg default` —— 破坏性操作。
5. **`/tmp` 是 tmpfs**：socket 重启即消失，`midcore` 由 `sysup`/`pslist` 拉起。

---

## 7. 证据索引

| 内容 | 地址/位置 |
|---|---|
| `main` | `0x112AC`（socket/bind/listen/select） |
| accept/select 循环 | `0x117FC` |
| 报文处理 | `0x11544`（64 字节首读、长度校验、分块发送） |
| opcode 分发 | `0x126DC`（switch 0..0x15） |
| 各操作 | `0x12168`(get) / `0x121F4`(test) / `0x1222C`(del) / `0x12260`(backup) / `0x122A4`(restore) / `0x12320`(default) / `0x12488`(commit) |
| socket | `/tmp/arc-middle/core_trnx` |
| 就绪标记 | `/tmp/.arca-midcore.ok` |
