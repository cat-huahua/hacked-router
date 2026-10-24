# Singtel async_event：netlink 订阅与 WAN 动作

材料：WG9116AEAC23-ST v5.02.00 build09b 的 `/usr/sbin/async_event`。
本文仅静态分析，不代表该进程正在设备上运行。

## 已解：订阅范围

`initStdNetlinkMonitorFd` 创建 `socket(16, 3, 0)`，即
`AF_NETLINK / SOCK_RAW / NETLINK_ROUTE`。传给 `bind` 的
12 字节 `sockaddr_nl` 为：

| 偏移 | 值 | 含义 |
|---|---|---|
| +0 | u16 16 | `nl_family = AF_NETLINK` |
| +2 | u16 0 | pad |
| +4 | u32 0 | `nl_pid = 0`，由内核分配 |
| +8 | u32 1 | `nl_groups = RTMGRP_LINK` |

没有订阅 IPv4/IPv6 地址、route 或 neighbor 组，也没有调用 `libarcnetlink`。
这是标准 route netlink 的 link monitor，不能与 `arc_netlink.ko` 的私有协议混为一谈。

## 已解：消息分发

`processStdNetlinkMonitor` 使用 4096 字节 iovec 和 `recvmsg(fd, &msg, 0)`。
逐条检查 `nlmsg_len >= 16`、不超过剩余长度，以 `(nlmsg_len + 3) & ~3`
推进指针。

| `nlmsg_type` | 分支 |
|---|---|
| 3 / `NLMSG_DONE` | 日志 `got DONE msg`，结束本次处理 |
| 2 / `NLMSG_ERROR` | 错误日志，结束本次处理 |
| 16 / `RTM_NEWLINK` | `updateLinkStatus()`，随后 `logLanStatus()` |
| 17 / `RTM_DELLINK` | 只执行 `logLanStatus()`，不更新 WAN 状态 |
| 其余 | 打印 `got %d (len=%d)`，继续下一条 |

**关键限制**：处理函数没有读取 `ifinfomsg` / `IFLA_*`，没有按事件中的
ifindex、接口名或 carrier 分发。任意 `RTM_NEWLINK` 都会促使它重新查询固定的 `eth0`。

## 已解：状态查询与动作

`getInterfaceStatus("eth0", &status)` 创建 `socket(2, 2, 0)`，通过
`ifreq.ifr_data` 指向局部整数，调用 `ioctl(fd, 0x89f1, &ifr)`。
返回值不为 -1 时读取该整数；非零归一化为 1。调用者事先把 `status` 清零。
这里不是通过 `SIOCGIFFLAGS` 或解析 netlink flags 取状态。

`updateLinkStatus` 使用一个初值为 0 的 `.bss` 全局状态，比较上次与当前值：

| 上次 → 当前 | `mng_action` 的两个字符串参数 |
|---|---|
| 0 → 1 | `("wan_start", "wan_idx=0")` |
| 1 → 0 | `("wan_stop", "wan_idx=0")` |
| 相同 | 只打印 `no cheange eth0_status=%d` |

变化时还向 `/dev/console` 写 `eth0 link up` / `eth0 link down`。
`fopen` 失败不阻止后面的 `mng_action`。函数最后保存当前状态。
没有检查 ioctl 失败的独立错误码，因此查询失败留下的 0 也可能被当作 down。

`logLanStatus` 仅运行如下诊断命令：

```sh
dmesg |grep link_speed|grep eth0|tail -1 > /tmp/lan_status
```

`async_event_init` 成功 bind 后立即执行一次 `updateLinkStatus`，之后
`main` 用无 timeout 的 `select` 等待 socket。`main` 先 `daemon(0, 0)`，
建立一次 `mapi_start_transc`；连接失败即退出。正常循环没有主动重连路径。

动作后续由 `/usr/share/msg/wan_start` / `wan_stop` 定义，涉及 WAN、DHCP、PPP、
IPv6、DDNS、LED 等已有事件总线流程，见 [启动事件总线](singtel-boot-event-bus.md)。
不能把一次 link 通知直接等同于 Internet 连通性变化。

## 未解与运行边界

- `0x89f1` 的驱动实现和返回整数的板级语义尚未追到 ioctl handler；本篇只确认调用方式。
- `arc_rcS` 中 `#async_event CMD_BOOT` 是注释；`/sbin/arc_async_event` 包装脚本
  可启动它，但有二进制和脚本不等于默认启用。实际运行情况需要设备 shell。
- 没有进行设备侧插拔、ioctl 失败或事件风暴测试。

## 证据索引

代码地址为 ELF VA；本文件可执行 LOAD 段的 file offset = VA - `0x10000`。

| 内容 | 符号 / VA | file offset / 字符串 |
|---|---|---|
| socket / bind / 组掩码 | `initStdNetlinkMonitorFd` `0x11020` | `0x1020`；组值写入 `0x110b4–0x110c0` |
| 接收、头检查、消息类型 | `processStdNetlinkMonitor` `0x11140` | `0x1140`；分发 `0x1124c–0x112d4` |
| 状态 ioctl | `getInterfaceStatus` `0x10e2c` | `0xe2c`；`movw r1, 0x89f1` 在 `0x10e88` |
| 两个动作与状态保存 | `updateLinkStatus` `0x10edc` | `0xedc`；`mng_action` 在 `0x10fb8` |
| 初次查询 | `async_event_init` `0x11370` | `0x1370` |
| 初始化与 select | `main` `0x10ad8` | `0xad8`；`select` `0x10c5c` |
| 固定接口、参数、动作 | `.rodata` | `0x148e` `eth0`；`0x14b1` `wan_idx=0`；`0x14bb` `wan_start`；`0x14d6` `wan_stop` |
| 诊断命令 | `logLanStatus` `0x10ecc` | 字符串 `0x1453` |
| 启动状态 | `/sbin/arc_rcS`、`/sbin/arc_async_event` | `#async_event CMD_BOOT`；`CMD_BOOT / CMD_START / CMD_RESTART` 分支 |

样本 SHA-256：`7a5f5fc4dd0d4425ccee98ad69bb9405448eb59eb4f962bb9d991cd9a0227e88`。

复核示例（`ROOTFS` 指向已提取的主路由 rootfs）：

```sh
readelf -sW "$ROOTFS/usr/sbin/async_event"
readelf -lW "$ROOTFS/usr/sbin/async_event"
r2 -q -e scr.color=0 -e bin.relocs.apply=true \
  -c 'aa; pdf @ sym.initStdNetlinkMonitorFd; pdf @ sym.processStdNetlinkMonitor; pdf @ sym.updateLinkStatus' \
  "$ROOTFS/usr/sbin/async_event"
```
