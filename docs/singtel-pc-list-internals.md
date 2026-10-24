# Singtel pc_list：备注名格式、共享表与 NAT 地址同步

材料：WG9116AEAC23-ST v5.02.00 build09b 的 `libpclist.so.0.1`、
`libumng.so.0.1` 和 `pc_list_daemon`。以下结论来自静态反汇编。
既有 LAN / WiFi Insight 概览见 [主机表与 WiFi Insight](singtel-lan-and-wifi-insight.md)。

## 已解：备注名的落盘格式

文件是 `/etc/config/pc_list_save`，通过 `libumng` 读写。
它不是 `.glbcfg` 数字 ID，也不是 UCI 的 `config / option` 语法。
序列化规则是 `@section\n`、逐项 `key=value\n`，最后 `!\n`：

```text
@manual_name
<小写冒号分隔 MAC>=<备注名>
!
```

尖括号都是占位符，不是文件中的实际内容。MAC 由
`%02hhx:%02hhx:%02hhx:%02hhx:%02hhx:%02hhx` 生成。

`umngcfg_commit` 先 seek 到文件开头，按上述格式分块 `write`，再
`ftruncate` 到实际写入长度，最后 `fsync`。没有看到对 key/value 中换行或
`=` 的转义；不能把它当作通用的带引号 INI 文件。
`umngcfg_open` 支持行首 `#` 注释、`@` section、首个 `=` 分割和 `!` 终止，
并处理 CRLF。commit 会重新生成内容，不保留原始注释。

### add / del / load

- `pc_list_client_set_manual_name(mac_bytes, name)`：打开共享表，再以模式 2
  打开备注文件；生成 MAC 文本；锁定表；找该 MAC，找不到就分配槽位；
  将名字复制到记录 `+0xb8`；调用
  `umngcfg_set(handle, "manual_name", mac_text, name)`，随后 `umngcfg_commit`，
  解锁并关闭。该路径没有单独设置 `+0x138` 的 used bit。
- `pc_list_client_del(mac_bytes)`：同样先找/分配槽位；清空记录 `+0xb8`，
  将状态 bits 5–6 设为 2、清 used bit；
  `umngcfg_unset(handle, "manual_name", mac_text)` 后 commit。
  它不执行 WiFi 踢客户端或 DHCP 租约删除。
- `pc_list_load_saved_manual_name(handle)`：以模式 1 打开文件，遍历
  `manual_name` section，解析 MAC，找/分配记录，写 `+0xb8`，并置 used bit。
  守护进程启动时加载；`pc_list_client_update` 在其进程内首次调用时也加载。

注意：这里描述的是调用顺序；这些函数并未完整检查 set/commit 等下层返回值，
不能把函数返回 0 当作已验证持久化成功。

## 已解：共享二进制表

`pc_list_open` 对 `/tmp/pc_list` 做 `open` / `ftruncate` / `mmap`：

- 总长 `0x21800 = 137216` 字节；256 个槽位；每个 `0x218 = 536` 字节。
- `mmap(PROT_READ|PROT_WRITE, MAP_SHARED)`；辅助函数 `0x143c` 用
  `fcntl(fd, 7, &flock)`，即阻塞式记录锁；锁类型 0/1/2 对应读/写/解锁。
- 返回 8 字节 wrapper `{fd, mapped_address}`，不是表头；文件本身直接从第一个记录开始。
- `pc_list_client_update` 返回 malloc 出来的完整 `0x21800` 字节副本。

已能逐字节确认的字段：

| 记录偏移 | 布局 / 用途 |
|---|---|
| `0x000` | IPv4 文本，后续字段从 `0x010` 开始 |
| `0x010` | IPv6 文本，后续字段从 `0x038` 开始 |
| `0x038` | 自动获取的 hostname，后续字段从 `0x0b8` 开始 |
| `0x0b8` | 手动备注名，后续字段从 `0x0d8` 开始 |
| `0x11c–0x134` | 7 个 32 位时间字段；daemon 输出时 month+1、year+1900 |
| `0x138` | flags：bits 0–2 介质、bits 3–4 地址类型、bits 5–6 状态、bit 7 used |
| `0x13c` | 32 位交换机 ARL 结果；`0xffffffff` 表示未找到，输出用 `%x` |
| `0x140` 起 | 无线统计区，仅对介质 2/3 且状态 1 的记录采集 |
| `0x210` | bits 0–1 保存上轮状态 |
| `0x211–0x216` | 6 字节 MAC |

上述字符串边界是相邻字段的起点，不等于调用者均做了长度验证。
没有 DWARF 类型名的字段以偏移描述，不虚构 C struct 名。

flags 的确定映射来自 daemon 的打印分支：

| 位域 | 编码 |
|---|---|
| 介质 | 1=`Wire`，2=`2.4G`，3=`5G`，其余打印 `Unknown` |
| 地址类型 | 0=`STATIC`，1=`DHCP`，其余 `Unknown` |
| 状态 | 1=`Online`，2=`Offline`，其余 `Unknown` |
| used | bit 7 非零才作为有效记录处理 |

有线的最终文本 Online/Offline 还结合额外查询和 ARL 结果；不能把 flags 的状态
直接等同于 daemon 所有分支的最终显示。`pc_list_update` 还会写介质编码 4，
但 daemon 的显示分支没有对应标签，暂保留原始编码。

`0x19cc` 槽位分配器先找 used=0 的槽位，再找状态 2，再找状态 0；
`0x1a3c` 按六字节 MAC 遍历整个表匹配。

数据流继续使用 `mapi_lanhs_get_hosts`、`/proc/net/arp`、
`ethswctl -c arl`、`wl -i ... sta_info`，IPv6 来自
`/proc/net/mac2v6addr` / `mac2v6lladdr`。`pc_list_daemon` 每轮休眠 10 秒，
还有按轮数触发的 ARP refresh / 更新分支；`/tmp/pc_list_tmp` 是打印出的文本，
不能用其文本行长推导共享表记录大小。

## 已解：port forwarding 的 IP ↔ MAC 同步算法

`port_forward_ip_mac_update(table_copy)` 接受表记录数组，开启 mapi transaction：

1. 读取 `ARC_NAT_PORTMAP_MaxNum` 并 `atoi`；读取 `ARC_NAT_PORTMAP_Enable`。
   仅当全局开关首字节为 `'1'` 才遍历 `i = 0 .. MaxNum-1`。
2. 每个槽读取 `ARC_NAT_PORTMAP_%d_Enable`，首字节非 `'1'` 则跳过。
3. 分别读取 `PrivateIP`（16 字节缓冲区）和 `PrivateMAC`（32 字节缓冲区）。
   有效性的判断只看 `strlen(IP)>6` 和 `strlen(MAC)==17`，没有在此调用地址校验器。
4. 按以下分支补齐或刷新配置。

| IP 文本长度 | MAC 文本长度 | 行为 |
|---|---|---|
| ≤6 | ≠17 | 跳过 |
| ≤6 | =17 | 用 MAC 在表中查 IPv4；直接 set `PrivateIP`，置 IP-changed 标志 |
| >6 | ≠17 | 用 IPv4 在表中查 MAC；set `PrivateMAC`，不置 IP-changed 标志 |
| >6 | =17 | 以 MAC 查当前 IPv4；结果非空且与旧 IP 不同才 set `PrivateIP` 并置标志 |

查找 helper 在库内 VA `0x18b8`：逐个跳过 used=0 的槽位；mode=0
按**区分大小写**的 MAC 文本 `strcmp` 找 IP，mode 非 0 按 IPv4 文本 `strcmp`
找 MAC。输出 MAC 用小写格式。helper 无论命中与否都返回 0，调用者不能用
返回值判断查找成功；未命中时输出缓冲区保持原值。

这意味着“缺 IP、仅有 MAC”分支会 set 未命中时保留的原 IP 文本并触发动作；
“缺 MAC、仅有 IP”分支也会 set 原 MAC 文本。两者没有成功标志检查。
仅“二者都有”分支用额外零初始化缓冲区检查查出的 IP 是否非空。

5. 如果 IP-changed 标志置位，仅调用一次：

```sh
mng_cli action ui_forward=forwarding_mod
```

只补 MAC 的分支没有触发该动作。动作发生在 `mapi_end_transc` **之前**；
本函数没有 `commit` 调用，不能据此声称这些配置修改已经持久化到 flash。

6. 尾部读取 `ARC_NAT_PORTMAP_IP6_MaxNum` / `ARC_NAT_PORTMAP_IP6_Enable`，
   随即结束 transaction；**没有 IPv6 遍历、匹配、写回或重建动作**。

### 尚未证实的运行调用链

本样本 rootfs 中对字符串 `port_forward_ip_mac_update` 的引用搜索只命中
`libpclist.so.0.1` 本身；`pc_list_update` / `pc_list_client_update` / daemon 的
已分析路径也没有调用它。已恢复的是该导出函数的完整算法，**尚无证据表明本固件
会周期性执行该同步**。动态拼接符号、其他加载路径或不同固件版本仍可能存在，
需要额外证据，不能把导出函数直接画成 daemon 的必经流程。

## 未解

- 共享记录的剩余字段和无线统计区尚未全部命名；上表仅列确定字段。
- NAT helper 的实际运行调用者、错误传播和 flash 持久化效果未证实。
- 未读取或公开任何实际客户端备注名、MAC、SSID 或凭据。
- 未在设备侧执行 add/del、NAT 修改或服务重载。

## 证据索引

以下 shared library 的所列 VA 与 file offset 相同；daemon 的可执行段
file offset = VA - `0x10000`。

| 内容 | 文件 / 符号 | VA / file offset / 字符串 |
|---|---|---|
| 共享表大小与 mmap | `libpclist` `pc_list_open` | `0x206c`；`0x209c` 比较 `0x21800` |
| 文件路径 / section / MAC 格式 | `libpclist` `.rodata` | `0x3261` `/tmp/pc_list`；`0x326e` `/etc/config/pc_list_save`；`0x3287` `manual_name`；`0x2fe8` MAC 格式 |
| 加载备注名 | `pc_list_load_saved_manual_name` | `0x21a4`，置 used bit `0x2294–0x229c` |
| 写备注名与 commit | `pc_list_client_set_manual_name` | `0x22e8`；`umngcfg_set` `0x23d0`，commit `0x23d8` |
| 删除备注 | `pc_list_client_del` | `0x2410`；`umngcfg_unset` `0x24fc`，commit `0x2504` |
| 共享表副本 | `pc_list_client_update` | `0x2c18` |
| MAC / IP 查找 helper | `libpclist` 无符号函数 | `0x18b8–0x19c4` |
| 槽位分配 / MAC 匹配 / 锁 | `libpclist` 无符号函数 | `0x19cc` / `0x1a3c` / `0x143c` |
| NAT 同步 | `port_forward_ip_mac_update` | `0x2ca8`；IP 写回 `0x2f30–0x2f3c`；动作 `0x2f50–0x2f58` |
| NAT 键 / 重建动作 | `libpclist` `.rodata` | `0x32fb–0x33c2`；`0x337e` `mng_cli action ui_forward=forwarding_mod` |
| `@`、`=`、LF、终止符及 fsync | `libumng` `umngcfg_commit` | `0x1328`；`0x1380` `0x40`，`0x1440` `0x3d`，`0x1570` `0x21`，`0x15d8` fsync |
| 文本解析 | `libumng` `umngcfg_open` | `0x15f4`；`0x16f4–0x17d8` CR / LF / `#` / `!` / `@` / `=` |
| flags 与文本输出 | `pc_list_daemon` `main` | VA `0x10dd4–0x10f94` / file `0xdd4–0xf94` |
| 轮询间隔 | daemon `main` | VA `0x10fbc–0x10fc0` / file `0xfbc–0xfc0`，`sleep(10)` |

样本 SHA-256：

- `libpclist.so.0.1`：`ef0a1575c2add28f3c56567a490a2f8635c829cff14564c1cee5b38a156d62fc`
- `libumng.so.0.1`：`1ef01c7ac91548ebf83e6f100cb999c184ed83f3c46218d29abb8ac1a731dcc9`
- `pc_list_daemon`：`01949e0fba0b9b5294cf83176f545e8fec81bc3d3ba004ce2bd90cef236e8694`

复核示例：

```sh
r2 -q -e scr.color=0 -e bin.relocs.apply=true \
  -c 'aa; pdf @ sym.pc_list_client_set_manual_name; pdf @ sym.port_forward_ip_mac_update' \
  "$ROOTFS/usr/lib/libpclist.so.0.1"
r2 -q -e scr.color=0 -e bin.relocs.apply=true \
  -c 'aa; pdf @ sym.umngcfg_commit; pdf @ sym.umngcfg_open' \
  "$ROOTFS/usr/lib/libumng.so.0.1"
```
