# Singtel Mesh Router 的 LED 与按键（GPIO）

> 设备：Arcadyan WG9116AEAC23-ST（v5.02.00 build09b，BCM963138）
> 材料：`/etc/gpio/led_map.txt`、`/etc/gpio/button_map.txt`、
> `/sbin/arc_ledd`、`/sbin/arc_gpiod`、`/sbin/arc_led`、`/sbin/arc_gpioctrl`
> 一句话：**按键全是低电平有效；GPIO32 按住 8 秒 = 恢复出厂；LED 由
> `arc_ledd` 用共享内存队列驱动。**

---

## 1. LED 映射（`/etc/gpio/led_map.txt`）

格式：`名字=GPIO,有效电平,初始状态`

| LED | GPIO | 有效 | 初始 | 含义 |
|---|---:|---|---|---|
| `power` | 26 | low | blink | 电源/系统状态（绿色） |
| `power_r` | 25 | low | — | 电源红灯 |
| `internet` | 15 | low | — | Internet（绿色） |
| `internet_r` | 22 | low | — | Internet 红灯 |
| `led_onoff` | 35 | low | — | LED 总开关指示 |
| `mesh` | 19 | low | — | mesh/回传（绿色） |
| `mesh_r` | 21 | low | — | mesh 红灯 |
| `ethernet` | 24 | low | — | 以太网 |

注释里还列了没启用的：`lan1..4`、`wlan24`、`wlan5g`、`fxs1/2`、`dect`、
`dsl`、`usb20/30`、`iptv_g/r`。

> **低电平有效**：`set 0` 才是亮，`set 1` 是灭。

---

## 2. 按键映射（`/etc/gpio/button_map.txt`）

格式：
```
名字=GPIO
active=low/high
spec=按住多少毫秒算长按
```

| 按键 | GPIO | 有效 | spec | 动作（从 `arc_gpiod` 字符串读出） |
|---|---:|---|---:|---|
| `wps` | 33 | low | 0 | 启动 WPS（`ui_wps_singtel`） |
| `reboot` | 32 | low | 0 | `reboot` |
| **`default`** | **32** | low | **8000** | **按住 8 秒 → `ui_factory_defaults`（恢复出厂）** |
| `led_onoff` | 34 | low | 0 | 开关 LED |
| ~~`dect_page`~~ | 34 | low | 0 | 本机型注释掉 |
| ~~`wlan`~~ | 26 | low | 1000 | 注释掉 |

★ **`reboot` 和 `default` 共用 GPIO32**，区别只在按住时长：
短按重启，按住 8 秒恢复出厂。`arc_gpiod` 里能看到：

```
default button clicked
arc_led power blink 250,250
ui_factory_defaults
```

> 这就是“为什么按住 reset 孔 8 秒会清空配置”的实现。

---

## 3. `arc_led` 命令

```
Usage: arc_led <ledname> <cmd> [option] [option1]

ledname    : led_map.txt 里定义的名字
cmd        : ecooff / econ / blkoff / blink
option     : blink 的持续时间（秒）
option1    : blink 的亮/灭毫秒数，例如 250,500
```

例子：

```sh
arc_led power blink 250,250     # 电源灯快闪（恢复出厂前的提示）
arc_led mesh blink 10 500,500   # mesh 灯闪 10 秒
arc_led mesh on                 # 常亮
arc_led mesh off                # 常灭
arc_led power blink 10 500,500  # 10 秒闪烁
```

（`arc_led` 的 usage 里把 `on/off` 归到 `econ/ecoff`，实际脚本里两种写法都有。）

---

## 4. `arc_ledd`（LED 守护进程）

`strings` 可见：

```
parse_mapping_file / insert_mapping
statq_init / statq_enq / statq_deq（共享内存 + 信号量队列）
blink / blkoff / econ / ecoff
/etc/gpio/led_map.txt
%s daemon start...
```

工作方式：

1. 读 `led_map.txt`，建立 `名字 → GPIO/有效电平/初始状态` 表；
2. 用 `shmget` + `semget` 建一个状态队列；
3. `arc_led` 把“点亮/熄灭/闪烁”命令塞进队列，`arc_ledd` 消费并操作 GPIO；
4. 支持 `blink`（周期闪烁）、`blkoff`（停止闪烁）、`econ/ecoff`（节能开关）。

---

## 5. `arc_gpiod`（按键守护进程）

除了按键，它还管：

| 功能 | 说明 |
|---|---|
| `ARC_SYS_SwitchMode` | auto/manual 模式开关（GPIO 电平变化），切换会 `reboot` |
| `ARC_SYS_MPTEST` | 工厂测试模式 |
| `simcard_plug` / `simcard_unplug` | SIM 卡插拔（LTE 机型） |
| `wlan_toggle` | WLAN 键 |
| `dect register/page` | DECT（本机型未用） |

**手动模式切换**：

```
detect automode switch change to [auto] mode
detect automode switch change to [manual] mode
reboot for automode change to [auto]
reboot for automode change to [manual]
```

即：拨动模式开关会让设备重启进入对应模式。

---

## 6. `arc_gpioctrl`（底层工具）

```
arc_gpioctrl get <pin>
arc_gpioctrl set <pin> <0/1>
arc_gpioctrl set_pinmux <pin> <val>
```

例子：

```sh
arc_gpioctrl get 26              # 读 GPIO26
arc_gpioctrl set 26 0            # 拉低（低有效 → 点亮 power）
arc_gpioctrl set_pinmux 26 5     # 把引脚复用成 GPIO 功能
```

⚠️ `set_pinmux` 写错会破坏该引脚的硬件功能（UART/开关/PCIe 等），
**不要随便试不认识的引脚**。

---

## 7. `arc_all_led`（红/绿全亮）

```sh
arc_all_led 0 r     # 红灯组：21 22 25
arc_all_led 0 g     # 绿灯组：15 19 24 26
arc_all_led 0       # 全部：15 19 21 22 24 25 26
```

它会先：

```sh
killall -q arc_iptvled_daemon
killall -q autowandetect
```

因为 LED 引脚和 IPTV/自动 WAN 检测有复用冲突。

---

## 8. 实用诊断

| 现象 | 可以看什么 |
|---|---|
| 电源灯常闪 | `arc_led power blink ...` 是恢复出厂前兆；检查是否卡在 `ui_factory_defaults` |
| mesh 灯不亮 | `arc_led mesh on`，或查 `arc_ledd` 是否在跑 |
| 按键没反应 | `cat /etc/gpio/button_map.txt`；`arc_gpiod` 是否在跑 |
| 想强制恢复出厂 | 按住 reset（GPIO32）**8 秒**，等 `power` 快闪 |
| 想临时关灯 | `arc_led <name> off`，或按 `led_onoff` 键（GPIO34） |

---

## 9. 安全/风险

1. **GPIO32 长按 8 秒 = 清空所有配置** —— 这是最容易误触的“破坏性操作”。
2. `arc_all_led` 会杀掉 `autowandetect`，可能影响 WAN 自动检测，别在正常运行时乱用。
3. `set_pinmux` 改错引脚可能让串口/交换机/PCIe 失效，**只在你确定引脚定义时用**。
4. 按键是低有效：用万用表/跳线短接 GPIO 到地会触发对应动作（包括恢复出厂）。

---

## 10. 证据索引

| 内容 | 位置 |
|---|---|
| LED 表 | `/etc/gpio/led_map.txt`（即 `usr/share/config/etc/gpio/led_map.txt`） |
| 按键表 | `/etc/gpio/button_map.txt` |
| LED 守护 | `/sbin/arc_ledd`（`/etc/gpio/led_map.txt`、`statq_*`） |
| 按键守护 | `/sbin/arc_gpiod`（`ui_factory_defaults`、`ui_wps_singtel`、`ARC_SYS_SwitchMode`） |
| LED CLI | `/sbin/arc_led`（usage 字符串） |
| GPIO CLI | `/sbin/arc_gpioctrl`（get/set/set_pinmux） |
| 全亮 | `/sbin/arc_all_led` |
