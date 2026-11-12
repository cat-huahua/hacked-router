# Extender DHCP 探测与正常 uplink 切换

## 已解

WE410443 的 `drv_atdp.ko` 会主动构造 DHCP DISCOVER，vendor class 为 `KPN Mesh DHCP Detect`。这是已启动 Linux 的 OWL/backhaul 探测逻辑，不是 bootloader recovery 的证据。捕获中 Ethernet source 与 BOOTP chaddr 不同，可以由实现解释：前者取 netdev 地址，后者使用固定探测常量。

2026-11-12 的私有抓包与静态实现对照：68 个探测包全部匹配固定 chaddr、固定 transaction ID、TTL=128、hardware length=6、seconds=24。具体地址、探测 hostname 与 transaction ID 不公开。约五秒的发送间隔也符合 daemon 代码。

`arc_atdp_app` 的 `arc_backhaul_dhcp_detect_daemon` 检查 `/tmp/dhcp_detect`；文件存在时每五轮（一轮 sleep 1 秒）调用 `libArc1905_send_dhcpc_discover_to_server(..., "eth2", 1)`。第二次发送时还报告 timeout；这是监控消息，不是 recovery 超时。

接收路径 `p19051_sniff_dhcp_trigger` 检查 IPv4/UDP、67/68 端口、DHCP cookie、首个 option 为 message type。OFFER 分支要求 chaddr 和 transaction ID 均匹配内置探测常量；它处理 BOOTP sname 中的 topology 标记，更新 checksum，并在探测 pending 时清除 pending 标志、发送 backhaul event 9。发送通知函数只接受 `eth2`，并设置消息偏移 `+0x53` 为 1。这里没有根据 OFFER 的 yiaddr 配置 IP，也没有处理 recovery URL。

`arc_atdp_app` 的 monitor switch 在现有 pseudocode 中未恢复，但原始汇编与 jump table 可补证 event 9：

- table index 9 指向 `0x00407f28`；检查 Ethernet link 状态和消息 `+0x53`。
- 成功分支在 `0x004080a4` 将 Ethernet uplink flag（interface 状态 `+0x48`）置 1，并进入 bridge/backhaul 更新流程。
- `arc_backhaul_check_uplink_existed` 在 interface `+0x22` 和 `+0x48` 都为 1 时返回 Ethernet uplink type 3。
- monitor 的公共 uplink 分支在 uplink type 改变时调用 `arc_backhaul_restart_dhcpc`，随后 `arc_backhaul_stop_dhcpd`。前者通过 `ui_dhcpc_restart` 动作启动正常 client；后者停本地 DHCP server。

因此，提供正常 upstream DHCP **可能**使设备从本地 DHCP server 角色切换为普通 Ethernet uplink/client；能否触发仍取决于实时 bridge、link、角色和其它状态。不能把对固定探测 chaddr 的 OFFER 当成已经分配给管理接口的 lease，也不能据此声称进入 recovery。

## 未解／边界

- 尚未做 OFFER 后的实时验证；没有证明所有 monitor switch 分支已恢复。
- 没有从此路径发现 recovery downloader、bootloader 改写或镜像签名绕过。
- 正常 uplink 后能否访问固件服务器，仍受 DHCP hook、DNS、系统时间、TLS 和镜像校验约束，参见 `singtel-extender-boot-access.md` 与 autofw 文档。

## 证据索引

| 对象 | 索引 | 作用 |
|---|---|---|
| `drv_atdp.ko` | SHA-256 `09754d3ffa20b4e6168257fd75b80c80ff903e938e53909a3e37ee4500f4242e` | 本文 kernel module 样本 |
| `_85` / `dhcp_discover_tx` | export analysis address `0x00019f18` | 构造 DISCOVER，字符串 `KPN Mesh DHCP Detect` |
| `_99` / `p19051_ARC_LINUX_sap_send_test_dhcpc_discover_packet` | analysis `0x00024334` | 设置 pending 并发送探测 |
| `_148` / `p19051_sniff_dhcp_trigger` | analysis `0x00025bd0` | OFFER 匹配与 event 9 |
| `_172` / `p19051_util_send_notification_to_backhaul_daemon` | analysis `0x0001fd5c` | eth2 检查，0x68-byte queue 消息 |
| `arc_atdp_app` | SHA-256 `392bf57f411f0b154c619806535af41bcf14e07556fc96a5e3bd7f8f879a4cd3` | userspace backhaul daemon |
| `arc_backhaul_dhcp_detect_daemon` | VA `0x004039a0` | `/tmp/dhcp_detect`，五秒探测 |
| `arc_backhaul_check_uplink_existed` | VA `0x00403e18` | Ethernet flag → type 3 |
| `arc_backhaul_monitor_daemon` | VA `0x00405c7c` | monitor；dispatch `0x00406910` |
| monitor jump table | VA `0x0040e1b4`，index 9 → `0x00407f28` | 使用 `_gp=0x00427370` 加 signed table entry 验证 |
| monitor event 9 | VA `0x004080a4` | 写 uplink flag=1；经 `0x00408660` 进入公共处理 |
| DHCP helper | VA `0x00404ba8` / `0x00404b60` | restart client / stop server |

ET_REL module 的 analysis address 是本次导出地址，不应直接当成设备 runtime VA 或原始文件偏移。上述用户态 VA 来自 MIPS ELF 的加载布局。私有 capture 仅公布字段匹配结果。
