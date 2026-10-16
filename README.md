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

**⚠️ 命令格式至今没解出来**（查表/JSON/带身份/zlib压缩/`?$[+`分隔符/以 reboot 当探针，
47+ 次尝试全部零反应）。payload 疑似还有一层封装或签名。要解开只能拿到**云端 agent 的
二进制**，而它在**加密的 rootfs** 里。

### ★ 固件与 bootloader

- [`docs/singtel-firmware-analysis.md`](docs/singtel-firmware-analysis.md) —— 加密地图、分区表、密码存储方式
- [`docs/uboot-web-recovery.md`](docs/uboot-web-recovery.md) —— ★ **u-boot 的 Web 恢复模式**（不鉴权，能写 bootloader）

### ★★★ 配置备份解密

- [`docs/netgear-config-decrypt.md`](docs/netgear-config-decrypt.md) —— **NETGEAR 的 `.cfg` 完全可解**
  （XOR + `rand()`，**种子就写在文件头里**）。工具：`netgear_r7800/ng_cfgdec.py`
- [`docs/huawei-config-format.md`](docs/huawei-config-format.md) —— 华为 `aescrypt2` 的完整格式与算法
  （**密钥在设备上，不在文件里**）
- [`docs/arcadyan-singtel-config-format.md`](docs/arcadyan-singtel-config-format.md) —— ★
  **Arcadyan / Singtel 的配置与密码机制**：glbcfg **是明文**、密码派生规则
  （`s1ngt3l` + 序列号后 6 位，已实证）、extender rootfs 为什么解不开（附完整证据链）

**三种设计的安全强度依次递增**：NETGEAR 把种子写在文件头里（所以能解）→
华为把密钥放设备上（一机一密）→ Arcadyan 把密钥放 bootloader 里（最靠下，最难拿）。

统一工具 `routercfg.py` 四种格式都认（含华为的 **HMAC 密钥验证器**）；
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
docs/           三份逆向笔记（登录锁 / 固件分析 / u-boot 恢复模式）
singtel_mesh/   Arcadyan mesh 工具集（★ 主要在这里）
hw_q2s/         华为 Q2S REST API 客户端
mqtt_spy/       假云端 MQTT broker（含 TLS）
acs/            假 TR-069 ACS + 极简 NTP 服务器
netgear_r7800/  NETGEAR SOAP API 客户端
```

**固件本体不进 git**（`.gitignore` 已排除 `*.trx`/`*.bin`/`*.sqsh` 等）。
