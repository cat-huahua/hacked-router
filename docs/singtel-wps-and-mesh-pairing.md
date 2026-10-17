# Singtel Mesh Router 的 WPS 与 mesh 配对

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b）
> 材料：`/bin/wps_monitor`、`/sbin/arc_wps_monitor`、`/sbin/arc_wps_led.sh`、
> `/usr/share/msg/WPS_*`、`.glbcfg`
> 一句话：**前传（用户 WiFi）的 WPS 默认关；回传（mesh）的 WPS 默认开，PIN 是 12345670。**

---

## 1. 组件

| 组件 | 作用 |
|---|---|
| `/bin/wps_monitor` | Broadcom WPS 状态机（WSC）：EAP-WSC、M1–M8、DH、TLV、加密设置 |
| `/sbin/arc_wps_monitor` | 启动/停止 `wps_monitor` |
| `/sbin/arc_wps_led.sh` | 轮询 `nvram get wps_proc_status`，控制 mesh LED |
| `/usr/share/msg/WPS_STATUS` / `WPS_CANCEL` | 动作消息 |
| `.glbcfg` 的 `ARC_WLAN_*_WPS_*` | 配置 |

`wps_monitor` 里的关键函数（`strings` 可见）：

```
state_machine_init_sm / state_machine_new
reg_msg_m1..m8 ap/sta parse/write
reg_proto_generate_dhkeypair / derivekey / encrypt_data / decrypt_data
reg_proto_generate_psk
tlv_credentialDelete / tlv_encrSettingsWrite
hmac_sha256 / SHA256
RAND_bytes / BN_new / DH_free
```

即完整的 WPS 注册协议（Registrar/Enrollee 两端都在）。

---

## 2. 启动与状态

`arc_wps_monitor`（boot 时）：

```sh
ps | grep wps_monitor ...        # 没有就起
/bin/wps_monitor &
```

`arc_wps_led.sh` 的状态码（Broadcom `wps_proc_status`）：

| 码 | 含义 | LED |
|---:|---|---|
| 0 | idle | 保持 |
| 1/5/6/7/9/10/11 | 进行中 | 慢闪 |
| 2 | **成功** | mesh 常亮 |
| 3/4 | 超时 / 错误 | 快闪 |
| 8 | PBC overlap | 快闪 |

超时 120 秒；结束后：

```sh
mng_cli tmp_set ARC_WLAN_WPS_Status="done"
```

如果 `ARC_WLAN_24G_SSID_0_WPS_Enable == 0`，脚本会
`killall -9 wps_monitor` —— **前传 WPS 关掉后连进程都不留**。

---

## 3. 出厂默认（`.glbcfg`）

### 3.1 前传（用户 WiFi，SSID_0）

```
ARC_WLAN_24G_SSID_0_WPS_Enable=0      ← 关
ARC_WLAN_5G_SSID_0_WPS_Enable=0       ← 关
ARC_WLAN_24G_WPS_Enable=1             ← 全局开
ARC_WLAN_24G_WPS_PINEnable=0          ← 不允许 PIN 方式
ARC_WLAN_24G_WPS_HwButtonEnable=0     ← 无硬件按钮
```

> 也就是说：**用户 WiFi 默认不能用 WPS 配网**（只能用网页/App）。

### 3.2 回传（mesh，STA / FH / BH）

```
ARC_WLAN_24G_STA_SSID_0_ESSID=Arc_Backhaul
ARC_WLAN_24G_STA_SSID_0_WPS_Enable=1
ARC_WLAN_24G_STA_SSID_0_WPS_ExRegistrarPIN=12345670
ARC_WLAN_24G_STA_SSID_0_WPA_Passphrase=12345678

ARC_WLAN_24G_FH_SSID_0_ESSID=Arc_Fronthaul
ARC_WLAN_24G_FH_SSID_0_WPS_Enable=1
ARC_WLAN_24G_FH_SSID_0_WPS_ExRegistrarPIN=12345670
ARC_WLAN_24G_FH_SSID_0_WPA_Passphrase=12345678

ARC_WLAN_24G_BH_SSID_0_ESSID=Arc_Backhaul
ARC_WLAN_24G_BH_SSID_0_Hide=0              ← ★ 不隐藏
ARC_WLAN_24G_BH_SSID_0_WPS_Enable=1        ← ★ 开
ARC_WLAN_24G_BH_SSID_0_WPS_ExRegistrarPIN=12345670
ARC_WLAN_24G_BH_SSID_0_WPA_Passphrase=12345678
```

5G 同理。

---

## 4. 运行时会被板级数据覆盖

`arc_glbcfg`（恢复出厂时）：

```sh
pin=`arc_board get wps-pin`
if [ 长度 == 8 ]; then
    设置 24G/5G SSID_0 的 WPS_ExRegistrarPIN = $pin
fi

wifi_24g_pwd=`arc_board get wifi-24g-pwd`
wifi_5g_pwd=`arc_board get wifi-5g-pwd`
wifi_bh_pwd=`arc_board get wifi-bh-pwd`
# 分别写入 SSID_0 / STA_SSID_0 / SSID_2 的 WPA_Passphrase
```

所以**正常出厂的设备**：

- 前传 PSK = 板级 `wifi-24g-pwd` / `wifi-5g-pwd`（一机一密）
- 回传 PSK = 板级 `wifi-bh-pwd`
- WPS PIN = 板级 `wps-pin`

**但如果板级数据丢失/损坏**（例如 SPI flash 被擦过、`/dev/brcmboard` 读不到），
设备就会退回 `.glbcfg` 的默认值：`12345678` / `12345670`。

---

## 5. Mesh 配对流程（从脚本和消息文件拼出来）

1. 主节点 `arc_wbd` 起 `wbd_master`，从节点起 `wbd_slave`；
2. `arc_ieee1905_owl` 加载 `arc_oshal.ko` + `drv_atdp.ko`，
   `arc_atdp_util init <bh_ssid> <al_mac> ...`；
3. 回传 AP（`wl1.2` / `wl0.2`）用 `Arc_Backhaul` + 板级 PSK；
4. 新节点用 WPS（PBC 或 PIN）加入回传；
5. 加入后 `wbd` 做 802.11k/v 的客户端引导；
6. 配置通过 `groups/<id>/desired_state`（云端）或本地 App 下发。

`WPS_STATUS` / `WPS_CANCEL` 两个消息文件就是 App/按钮控制 WPS 会话的入口。

---

## 6. 安全观察

1. **回传 SSID 不隐藏 + WPS 默认开 + PIN 出厂固定 12345670** ——
   如果板级 `wps-pin` 没有覆盖（或攻击者能触发默认值），
   回传网络存在 **WPS PIN 攻击**面。
2. **回传 PSK 默认 12345678** —— 同上，板级数据缺失时回传是可预测的。
3. **前传 WPS 默认关**，这点是好的；`WPS_PINEnable=0` 也减少了 PIN 攻击面。
4. **Broadcom WPS 的已知问题**：WPS PIN 的校验分成两半，可被离线/在线爆破
   （Reaver 类工具）。只要回传 WPS 开着，就有这个风险。
5. **`wps_monitor` 的随机数**：代码里 `RAND_bytes`（OpenSSL）用于 DH，
   但同时有 `srand()` 调用 —— 如果某条路径用 `rand()` 生成 nonce，
   随机性会弱很多。**这一点只从符号判断，没有逐函数确认，别当结论。**

### 怎么关掉回传 WPS（如果有 root）

```sh
mng_cli set ARC_WLAN_24G_BH_SSID_0_WPS_Enable=0
mng_cli set ARC_WLAN_5G_BH_SSID_0_WPS_Enable=0
mng_cli set ARC_WLAN_24G_FH_SSID_0_WPS_Enable=0
mng_cli set ARC_WLAN_5G_FH_SSID_0_WPS_Enable=0
mng_cli set ARC_WLAN_24G_STA_SSID_0_WPS_Enable=0
mng_cli set ARC_WLAN_5G_STA_SSID_0_WPS_Enable=0
mng_cli commit
```

（关掉后 mesh 自动配对会失效，需要手动配回传。）

---

## 7. 证据索引

| 内容 | 位置 |
|---|---|
| WPS 状态机 | `/bin/wps_monitor`（`reg_msg_m1..m8`、`reg_proto_*`） |
| 启动/停止 | `/sbin/arc_wps_monitor` |
| LED/状态码 | `/sbin/arc_wps_led.sh` |
| 默认值 | `.glbcfg` 的 `ARC_WLAN_*_WPS_*` / `*_WPA_Passphrase` |
| 板级覆盖 | `/sbin/arc_glbcfg`（`arc_board get wps-pin` / `wifi-*-pwd`） |
| mesh | `/sbin/arc_wbd`、`/sbin/arc_ieee1905_owl` |
