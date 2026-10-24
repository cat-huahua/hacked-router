# 暴力枚举 Singtel 配置键：38,193 个可能键 + 隐藏 JSON API

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`libarccfg.so`、`.glbcfg`、`httpd`
> 方法：**把字段表按索引上限全部展开**，再和 `.glbcfg` 比对。
> 工具：`cfgkeys.py`

---

## 1. 怎么“暴力”展开

`libarccfg.so` 的字段表每项 32 字节：

```
[名字指针][格式串指针][idx1 上限][0][idx2 上限][0][0][0]
```

格式串里的 `%d` / `%02d` 是索引。把每个模板按 `idx1 × idx2` 全展开：

```bash
python3 cfgkeys.py <rootfs> --missing    # 表里有、glbcfg 没有
python3 cfgkeys.py <rootfs> --unmapped   # glbcfg 有、表里没生成
python3 cfgkeys.py <rootfs> -o keys.txt  # 全量
```

实测：

```
模板 2,155 个
→ 展开出 38,193 个可能键
.glbcfg 实际只有 2,361 个
表里有、glbcfg 没有：36,135 个   ← 未使用的索引
glbcfg 有、表里没生成：303 个     ← 特殊表/%s 模板
```

---

## 2. 36,135 个“未使用索引”

大部分是给多实例预留的槽位，例如：

```
ARC_DDNS_0..19_*            20 组
ARC_WAN_0..3_*              4 组
ARC_WLAN_*_SSID_0..3_*      4 组 / 每频段
ARC_QOS_RULE_0..31_*
ARC_NAT_PORTMAP_0..19_*
```

这些键**可能可以 `mng_cli get`**（返回空或默认值），
也可能被服务读取。想找“没界面的开关”，这里是第一站。

---

## 3. ★ 303 个 `.glbcfg` 有、字段表没生成的键

按模块分布：

| 模块 | 数量 | 模块 | 数量 |
|---|---:|---|---:|
| WLAN | 133 | IPSEC | 8 |
| WAN | 41 | USB | 8 |
| LAN | 29 | OTHER | 8 |
| IP6 | 28 | SSHD | 3 |
| SYS | 20 | VPN | 3 |
| FIREWALL | 9 | NAT | 2 |
| | | OWL / TR69 | 2 / 2 |

### 值得注意的隐藏键

| 键 | 默认 | 含义 |
|---|---|---|
| **`ARC_HTTPD_JSONAPI_Enable`** | **0** | ★ **隐藏的 JSON API 总开关** |
| `ARC_3rd_EmbedUR_Enable` | 1 | 云代理 |
| `ARC_ROOT_Passwd` | — | root/SSH 口令（MD5） |
| `ARC_SSHD_Enabled` / `_Iface` / `_Port` | 0 / LAN / 22 | SSH |
| `ARC_TELNETD_ENABLE` | 0 | telnet |
| `ARC_TR69_UpgradeAutoRebootEnable` | 0 | TR-069 升级后自动重启 |
| `ARC_FIREWALL_BlockActivex/Cookie/JAVA/Loopback/Proxy` | — | 老式网页过滤开关 |
| `ARC_FIREWALL_IdentPass` | — | Ident 放行 |
| `ARC_IP6_6RD_*` / `6TO4_*` | — | IPv6 隧道 |
| `ARC_IP6_EnableNAT64/NAT46` | 0 | NAT64/46 |

---

## 4. ★★ `ARC_HTTPD_JSONAPI_Enable`：隐藏的 JSON API

`httpd` 里有一整套 JSON API，默认 **关闭**：

```
ARC_HTTPD_JSONAPI_Enable=0
```

打开后（需要 httpd 重启）会暴露：

```
json.cgi
/json
/api/
```

### 4.1 API 函数（字符串里全部列出）

```
json_get_system_info
json_get_lan_info
json_get_wl_settings
json_set_wl_settings
json_get_wl_bandsteering
json_set_wl_bandsteering
json_get_wl_mac_filter_list
json_set_wl_mac_filter_list
json_get_wl_channel_capacity
json_get_wl_recommended_channel
json_get_wl_site_survey
json_trouble_shooting
get_json_api_list
```

即：

- 读：系统信息、LAN 信息、WLAN 设置、band steering、MAC 过滤、
  信道容量、推荐信道、site survey、trouble shooting；
- 写：WLAN 设置、band steering、MAC 过滤。

### 4.2 请求格式

错误字符串：

```
input_json_num = [%d] error!
json parse name error!  i,input_json_num=[%d,%d]
json parse type error!  i,input_json_num=[%d,%d]
json parse val  error!  i,input_json_num=[%d,%d]
json request is ##%s##
```

说明请求是一个 **JSON 数组**，每项有 `name` / `type` / `val`：

```json
[
  {"name": "...", "type": "...", "val": "..."},
  ...
]
```

`input_json_num` 是数组长度；解析器逐项校验。

### 4.3 鉴权

- 同一套 **`httoken`** 一次性 token（和 web 登录一样）；
- `arc_json_verify` 负责校验；
- 错误串里有 `[%s] failed to pass token checking`。

### 4.4 怎么开/关

```sh
mng_cli set ARC_HTTPD_JSONAPI_Enable=1
mng_cli commit
# 然后重启 httpd（或整机）
```

> ⚠️ 打开后，任何能拿到 httoken 的本地/登录会话都能读写 WLAN 设置。
> 关掉就是 `=0` + commit + 重启 httpd。

---

## 5. 还能怎么“暴力”

1. **逐个 `mng_cli get`**：对 36,135 个键做一次只读探测，
   记录非空/非默认的键 —— 能画出“这台设备实际用了哪些隐藏字段”。
2. **`mng_cli test`**：验证值是否合法，能反推字段类型（int/string/IP）。
3. **索引上限探测**：对每个模板试 `idx+1`，看是否返回越界错误，
   可以确认真正的上限（表里的上限可能是保守值）。
4. **JSON API 打开后枚举 `get_json_api_list`**：它会返回可用 API 列表。

---

## 6. 安全观察

1. **JSON API 默认关**，但开关就在 `.glbcfg` 里，拿到 root 就能开。
2. **JSON API 能写 WLAN 设置和 MAC 过滤** —— 打开后等于多一个管理面。
3. **`ARC_ROOT_Passwd` 是明文配置项**（MD5 形式），和 SSH 开关一起看。
4. **36k 个未使用索引**里可能藏着未公开的调试/工厂字段；
   `mng_cli get` 是只读的，可以安全探测。
5. **`ARC_3rd_EmbedUR_Enable=1`** 已默认开启，是另一个独立管理面。

---

## 7. 证据索引

| 内容 | 位置 |
|---|---|
| 字段表 | `libarccfg.so` 的 `arc_*_cfg_item_table` |
| 展开工具 | `cfgkeys.py` |
| JSON API 开关 | `.glbcfg` → `ARC_HTTPD_JSONAPI_Enable=0` |
| JSON API 端点/函数 | `httpd` 字符串：`json.cgi`、`json_get_*`、`json_set_*` |
| 请求格式 | `input_json_num`、`json parse name/type/val error` |
| 鉴权 | `httoken`、`arc_json_verify` |
