# WE410443-ST：原厂 shell 入口与当前前提

核对日期：2026-11-12；样本 v6.02.00 build14。本篇区分固件内的服务能力、出厂默认配置与本次连接观测。没有获得设备 shell，没有尝试密码、改配置或执行固件代码。

## 已确认：SSH / Telnet 默认关闭

出厂 `usr/share/config/etc/config/glbcfg.dft` 包含：

| 配置键 | 出厂值 | 含义 |
|---|---|---|
| `ARC_SSHD_Enabled` | `0` | SSH 未启用 |
| `ARC_SSHD_Port` | `22` | 配置的 SSH 端口 |
| `ARC_SSHD_Iface` | `LAN` | 配置的绑定侧 |
| `ARC_SYS_TelnetdEnable` | `0` | Telnet 未启用 |

这些是样本的默认值，不等于读取到了设备当前持久配置。

`arc_sshd` 在 disabled 分支提前返回；启动时读取端口及 LAN/WAN/bridge 地址，最后以 `dropbear -p %s%u` 启动。端口解析为0时回退22；代码还有22/2222与 WAN NAT port-conflict 的处理，因此2222可作为有代码依据的有限检查候选，不代表它必定监听。`ui_sshd` 的本机事件脚本会 stop/start 服务，但尚未确认免认证的远程配置入口。

`arc_telnetd` 只有读取到 `ARC_SYS_TelnetdEnable=1` 才启动。它实际使用 `telnetd -l /bin/sh`，而 `/bin/login` 启动行被注释。这意味着该功能若被启用，会直接运行 shell；但**默认关闭的服务不能被宣称是现成免登录入口**。本轮没有启用它，也未公开任何凭据准备脚本的内容。

`update_sshd_shell.sh` 会在本地启动流程中调整持久 passwd 的 shell 字段；存在这个脚本不证明外部能绕过认证。Dropbear 密码认证模板与实际 daemon 启动配置也应分开核对。

## 本次连接观测与身份核对

2026-11-12，对直连 USB 网卡的候选地址做有限 TCP 检查，22/2222/23/2323拒绝连接，80/443接受连接。
用户随后提供机身标签 MAC，与该网卡的邻居记录一致，解决了家庭网络其他设备使用相同IP造成的归属疑问。
具体设备标识仅保存在私有记录中。复查 HTTP 根路径返回302，跳转到同一设备的HTTPS。

这些观测不能证明进入recovery，也没有提供shell。没有登录、改写配置或上传固件。

## 已确认：UART 配置指向 login

`preinit` 生成的 `/etc/inittab` 包含：

```text
tts/0::askfirst:/bin/login
ttyS1::askfirst:/bin/login
```

`/bin/login` 和 `/bin/sh` 都指向 BusyBox。此前 raw kernel 已确认 `console=ttyS1,57600n8`，见 [boot access 证据](singtel-extender-boot-access.md)。这是串口选择与 baud 的证据，**不是 UART 无密码 root shell 的证明**。

板上 pinout、电压、实际 boot log 与 login 行为尚未核对；不能仅凭 tty 名称猜接线。也不能假定 UART、SSH 与 Web 使用相同凭据。

## 未解与下一步前提

- 当前没有可执行 `iwpriv` 的 shell。合法管理配置入口、已有账户认证或 UART console 是后续需核实的条件。
- 没有确认可用的未认证网络 shell、recovery shell 或 bootloader 交互入口。
- DNS/WAN 重定向不会自行启动已关闭的 SSH/Telnet；升级客户端、TLS、镜像验证与 recovery 是独立路径。
- MCU ROM 读取接口即使存在于 driver，也需要本地执行权限；获得 host shell 不保证 MCU ROM 可读或 key 可导出。

## 证据索引

| 文件 / 符号 | 位置与证据 |
|---|---|
| `glbcfg.dft` | 上表四个配置键，原厂 rootfs 模板 |
| `sbin/arc_telnetd` | 文本脚本：enable==1 分支及 `telnetd -l /bin/sh`；其余敏感准备内容不公开 |
| `arc_sshd` | SHA-256 `dc02a37039ae88ff7603ac48655ec7961cced555801e72fd1f4b0823535450d9` |
| SSH 比较字符串 | file `0x29bc` 为 `0`；`0x29fc` 为 `port`；`0x2a60/0x2a78` 为 `LAN/WAN` |
| SSH 端口选择 | assembly VA `0x4017dc–0x401c78`，22/2222特殊分支及冲突处理；RX file offset=VA−`0x400000` |
| `preinit:main` | VA `0x4006d0`，创建 inittab 并写入两条 askfirst login 项 |
| `sbin/preinit` | SHA-256 `7d588552093153f6f043387bc32abbc87655700bc2e4e406331ea415e6496550` |
| UART console | raw kernel 的 cmdline，详见 boot-access 文档；非实际 UART capture |

原始 decompiled C/ASM、文件身份和连接观测留在私有
`router-notes-private/mcu-dump-plan-20261112/`；不公开设备地址、节点标识、口令或 key。

## 2026-11-12 直连接口观察补充

一次已停止的过滤抓包覆盖约342秒，共1263个packet，snaplen为512 bytes。
967个DNS查询均由电脑发向设备，未见设备主动查询已知更新域名，也未见设备主动建立TCP连接。
同时记录11组电脑的DHCPREQUEST与设备ACK；另外68个Discover的Ethernet来源与标签MAC相近，
但BOOTP client地址不同，客户端身份未确认，不能将其认定为recovery请求。

观察没有覆盖启动或重启，不排除其他接口、其他时段的更新流量。此次HTTPS页面检查也包含在抓包中。
抓包已由用户停止；原始流量及设备标识留在私有 `mcu-dump-plan-20261112/`，不上传。
这些证据不足以启动面向未知客户端的DHCP/DNS服务，也不证明已有修改镜像接受链。
