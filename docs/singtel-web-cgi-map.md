# Singtel Mesh Router 的 web 端点与 CGI 函数地图

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`httpd` 字符串 + `www/` 页面
> 目的：把 web 侧所有 `.cgi` 端点、`get_*`/`set_*` 函数列清楚。

---

## 1. 端点（`.cgi`）

| 端点 | 作用 |
|---|---|
| `/login.cgi` | 登录（httoken + ArcMD5） |
| `/logout.cgi` | 登出 |
| `/setpwd.cgi` | **正常改密**路径（真正写密码） |
| `/setpwd2.cgi` | 强制改密路径（`change_pwd.htm` 用，见 README） |
| `/apply_abstract.cgi` | 抽象配置应用（批量提交） |
| `/get_info.cgi` | 系统信息 |
| `/get_topology_clients.cgi` | 拓扑客户端 |
| `/json.cgi` | ★ 隐藏 JSON API（`ARC_HTTPD_JSONAPI_Enable=0` 默认关） |
| `/owl_cmd.cgi` | OWL/SON 命令 |
| `/upload.cgi` | 通用上传（固件/配置/文件） |
| `/upload_torrent_file.cgi` | BT 种子上传 |
| `/vpnupload.cgi` | VPN 配置上传 |
| `/bh.cgi` | backhaul |
| `/bs_settings.cgi` | band steering 设置 |
| `/lte_settings.cgi` | LTE 设置 |
| `/lte_warn.cgi` | LTE 警告/确认 |
| `/mt.cgi` | ★ manufactory test（工厂测试类，慎用） |

页面侧还能看到：

```
/index.htm  /login.htm  /logout.htm  /change_pwd.htm
/reboot.htm /factory_reset.htm /backup.htm /restore.htm
/upgrade.htm /json.cgi /owl_status.htm /owl_devices.htm /owl_discs.htm
```

---

## 2. `get_*` 信息函数

从 `httpd` 字符串里能列出：

```
get_system_info          get_cpu_mem_stat        get_sys_uptime
get_lan_info             get_lan_status          get_lan_address
get_lan_dev_info         get_pclist              get_mac_from_ip
get_wan_info             get_wan_ip              get_wan_mac
get_wan_dns              get_wan_address         get_wanif_index
get_internet_status      get_isp_status          get_con_type
get_dsl_status           get_lte_status          get_lte_traffic
get_ipv6_info            get_ipv6_localaddr      get_ipv6_prefixaddr
get_wl_settings          get_wl_bandsteering     get_wl_channel_capacity
get_wl_recommended_channel  get_wl_site_survey   get_wl_mac_filter_list
get_wl_clients_rssi_info get_wl_antenna_count
get_client_list          get_connected_device(s) get_topology_info
get_topology_clients     get_dev_traffic         get_packets_info
get_dpi_info             get_usb_dev_entries     get_usb_dev_entries2
get_usb_printers         get_usb_bt_info         get_disk_info
get_folder_list_in_media get_file_info
get_ovpn_client_name     get_vpn_openexport      vpn_connect_status
get_ddns_status          get_singleforward       get_basemac
get_sn                   get_model_name          get_hwver
get_tcode                get_boot_version        get_firmware_version
get_firmware_short_version  get_firmware_title   get_time
get_pin_info             get_SIPP_call_cnt       get_SIPP_call_log
get_SIPP_status          get_stb_assigned_info   get_mdns_list
get_netbios_list         get_band_steering_info  get_ethlink_status
get_lang                 get_nonce_num           get_mill_sec
```

---

## 3. `set_*` 动作

```
set_connection           set_factory_default     set_reboot
set_wl_settings          set_wl_bandsteering
set_wl_mac_filter_list   set_wl_recommended_channel
setpwd_cgi / setpwd2_cgi
```

---

## 4. 认证/安全辅助

```
check_auth               check_blacklist         check_default_passwd
get_login_wait_sec       get_password_encode_key / getPasswordEncodeKey
httoken / httoken_get / httoken_decode / httoken_lookup_ex
cgi_token_pass / url_token_pass
```

- `httoken`：一次性 token（每个请求都换）；
- `get_login_wait_sec`：登录锁倒计时（`wait_secs`）；
- `check_blacklist`：黑名单；
- `get_password_encode_key`：web 密码编码用的 key 提供函数。

---

## 5. 值得注意的端点

### 5.1 `mt.cgi`

名字像 **manufactory test**（工厂测试）。同厂 httpd 里有
`manufactory_testing_cgi` 一类调试入口的先例（见私有笔记，不在这里给参数）。
**不要在生产设备上盲试。**

### 5.2 `json.cgi`

隐藏 JSON API，默认关闭，见
[singtel-config-key-universe.md](singtel-config-key-universe.md)。

### 5.3 `setpwd.cgi` vs `setpwd2.cgi`

- `setpwd.cgi` = 正常改密（真正写 `passwd`/`ARC_SYS_Password`）；
- `setpwd2.cgi` = 强制改密闸门（只清“必须改密”标志，可能不写密码）。

这正是 README 里“管理密码为什么改不了”的根因。

### 5.4 `apply_abstract.cgi`

“抽象配置应用” —— 一次提交多个页面字段，内部会走 `mng_cli set` + commit。

### 5.5 `owl_cmd.cgi`

把 web 操作转成 OWL 命令（拓扑/漫游/LED）。

### 5.5 `upload.cgi` 的字段分派

`upload.cgi` 是 multipart 上传，靠 **表单字段名** 区分用途：

| 字段名 | 类型码 | 用途 |
|---|---:|---|
| `name="restore"` | 2 | **配置恢复**（`mapi_ccfg_restore`） |
| `name="plcfile"` | 6 | **固件升级**（共享内存 + `fw_upgrade`） |
| `name="file"` | 1 / 4 | 按该行是否含 `.rom` 分别调用同一 helper 的 mode 0 / 1 |
| 未命中且扫描结束 | 3 | fallback / 错误路径；外部可达条件待核对 |

反汇编（`0x25FF0`–`0x260B8`）先检查 `name="file"`，然后检查 restore / plcfile：

```c
if (strstr(header, "name=\"file\""))
    type = strstr(header, ".rom") ? 4 : 1;
else if (strstr(header, "name=\"restore\"")) type = 2;
else if (strstr(header, "name=\"plcfile\"")) type = 6;
// 未命中时继续扫描；扫描结束后走 type 3 路径。
```

同一个 `upload.cgi` 分派固件与配置恢复。非固件分支的固定临时文件、
restore → commit → reboot 顺序和错误判断见
[配置上传分析](singtel-httpd-config-upload.md)。

### 5.6 `cli_tbl` 不是 CGI 表

`httpd` 里的日志格式串：

```
cli_tbl[%d]=[%s], from=[%d], ip=[%s], name=[%s]
```

顺着 `movw sl,0x9928; movt sl,4` 找到引用点（`0x1D77C`）后确认：
它是 **`get_client_list()` 的客户端列表** 的打印逻辑：

```
entry 大小 0x70（112 字节）
  +0x50  名称字符串
  +0x68  值/来源
```

也就是说 `cli_tbl` 是“客户端信息表”，**不是 CGI 命令分发表**。
CGI 命令的分发是分散在各 `*_cgi` 函数里的，没有一张统一的 handler 表。

---

## 6. 安全观察

1. `.cgi` 端点全部依赖 `httoken`；没有 token 直接 302/失败。
2. `mt.cgi` 是工厂测试面，**默认可能仍可访问**（取决于编译/鉴权），值得单独确认。
3. `json.cgi` 默认关，但开关在配置里。
4. `get_password_encode_key` 说明密码在前端不是明文传输，但具体是
   `ArcMD5` 还是别的编码，要看页面 JS（已在 README 里确认是 ArcMD5）。
5. `upload.cgi` 同时处理固件/配置/文件，**上传类型靠参数区分**，
   历史上这类接口最容易出路径穿越/类型混淆问题。

---

## 7. 证据索引

| 内容 | 位置 |
|---|---|
| 端点 | `httpd` 字符串里的 `*.cgi` |
| `get_*`/`set_*` | `httpd` 字符串 |
| 认证 | `httoken*`、`check_auth`、`get_login_wait_sec` |
| 隐藏 JSON API | `json.cgi`、`ARC_HTTPD_JSONAPI_Enable` |
| 密码路径 | `setpwd.cgi` / `setpwd2.cgi` |
| 工厂测试 | `mt.cgi`（未验证） |
