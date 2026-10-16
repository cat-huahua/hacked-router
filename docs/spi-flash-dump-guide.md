# SPI Flash 读取指南 —— 唯一能突破那三条的路

**为什么写这份**：目前有三样东西解不开，而它们**卡在同一个地方**：

| 目标 | 卡在哪 |
|---|---|
| 华为 Q2S 的 `.conf` | 密钥 `hex:...` 在设备 `/etc/wap/aes_string` |
| Singtel extender 的 rootfs | 密钥在 flash 的 `u-boot`(0x0)–`u-boot-env`(0x30000) |
| extender 的 MQTT 命令格式 | 解码器（云 agent）在加密的 rootfs 里 → 同一个密钥 |

**这三个的钥匙都在同一块 SPI flash 芯片里。** 把 flash 读出来，三个一起解开。

> ⚠️ **前提**：只对**你自己拥有**的设备做。见 [NOTICE.md](../NOTICE.md)。
> 拆机可能影响保修；在板读取（in-circuit）需要设备**完全断电**。

---

## 一、要准备什么

| 东西 | 说明 | 大概价钱 |
|---|---|---|
| **CH341A 编程器** | 最常见最便宜，USB 转 SPI | ¥15–30 |
| **SOP8 / SOP16 测试夹** | 在板读取用，不用焊（先确认你芯片的封装！） | ¥10–20 |
| 杜邦线 / 排针 | CH341A 到夹子的连接 | — |
| 备用方案：热风枪 | 实在夹不住就吹下来读 | — |

**软件**（Linux 下）：

```bash
sudo apt install flashrom
```

**先打开设备看芯片丝印**，确认：
- 容量（本机 extender 的 flash 是 **32MB NOR**，见 `we410443.dts`）
- 封装（SOP-8 还是 SOP-16，引脚数决定买哪种夹子）
- 型号（Winbond W25Q 系列之类）

## 二、读之前：先备份，读两遍

```bash
# ① 设备【完全断电】：拔电源、拔电池（若有）、USB 也拔掉
# ② 夹子夹住 flash（注意 Pin1 方向！丝印上通常有个圆点）
# ③ 探测芯片
sudo flashrom -p ch341a_spi

# ④ 读第一遍
sudo flashrom -p ch341a_spi -r dump1.bin
# ⑤ 再读一遍
sudo flashrom -p ch341a_spi -r dump2.bin
# ⑥ ★ 两遍必须一致 —— 不一致说明接触不良，重夹重读
md5sum dump1.bin dump2.bin
```

**读两遍比对是必须的。** 在板读取时其它电路会干扰，读出不稳定的数据；
如果不比对就往下分析，你会花几个小时去破一段本来就错的字节。

> 拿到 dump 后**先复制一份留档**（`cp dump1.bin flash-original.bin`），
> 后面所有分析都在副本上做，原片不要动。

## 三、Flash 分区（来自 OpenWrt 的 `we410443.dts`，32MB NOR）

```
0x000000  192KB   u-boot          ← ★ rootfs 的解密密钥在这里（或它引用的地方）
0x030000   64KB   u-boot-env      ← ★ 先看这里：密钥可能是里面的一个环境变量
0x040000   64KB   factory         ← 射频校准
0x050000  31.4MB  firmware
0x1FB0000  64KB   glbcfg          ← ★ 明文配置（WiFi 口令在这里）
0x1FC0000  64KB   config          ← ★★ 管理密码 ARC_SYS_Password 就在这，【明文】
0x1FD0000  64KB   glbcfg2
0x1FE0000  64KB   config2
```

## 四、拿到 dump 之后怎么用（按性价比排序）

### ① 直接读明文密码 —— 最快，不用破任何东西

```bash
# config 分区：同厂设备的实测结论是【管理密码明文存在这里】
dd if=flash-original.bin of=config.bin bs=1 skip=$((0x1FC0000)) count=$((0x10000))
strings -a config.bin | grep -E 'ARC_SYS_Password|ARC_ROOT_Passwd|WPA_Passphrase|ARC_UI_WEB'

# glbcfg 分区同理（明文 key=value）
dd if=flash-original.bin of=glbcfg.bin bs=1 skip=$((0x1FB0000)) count=$((0x10000))
head -c 400 glbcfg.bin
```

**这一条很可能不用破任何哈希，直接就看到密码了。**
（同厂设备的 `glbcfg.dft` 实测就是纯 ASCII。）

### ② 找 rootfs 的 AES 密钥 → 解开 extender 的 rootfs

```bash
# u-boot-env：先当"人话"看
dd if=flash-original.bin bs=1 skip=$((0x30000)) count=$((0x10000)) | strings -a | head -40
# 形如 bootargs=... aes_key=... 之类，直接就是答案

# u-boot 本体：找 AES 实现与密钥
dd if=flash-original.bin of=uboot.bin bs=1 count=$((0x30000))
strings -a uboot.bin | grep -iE 'aes|key|decrypt|rootfs|arcadyan|password'
# 找 AES 的 S 盒 / T 表（定位实现），密钥通常在附近的 .rodata 里：
python3 - <<'EOF'
import pathlib, re
d = pathlib.Path("uboot.bin").read_bytes()
for n, m in [("正S盒", bytes.fromhex("637c777bf26b6fcf3001672bfed7ab76")),
             ("逆S盒", bytes.fromhex("52096ad53036a538bf40a39e81f3d7fb")),
             ("Td0",   bytes.fromhex("51f4a7507e4165531a17a4c33a275e96"))]:
    print(n, [hex(x) for x in re.finditer(re.escape(m), d)] or "未找到")
EOF
```

拿到候选密钥后，用本仓库已有的判据测：

```bash
# 假设密钥是 16 字节 hex，做成 32 字符的候选，然后：
# 用 routercfg.py 或直接试解 squashfs 的第一个数据块，看能不能变成 xz 流头
# （判据：解出来应出现 fd 37 7a 58 5a 00，即 XZ 魔数）
```

**测密钥时的判据要硬**（这是本仓库踩过的坑）：
- ✅ "解出来出现合法魔数 / 能 unsquashfs 成功" —— 硬判据
- ❌ "unsquashfs 报了一句话" —— **软判据，会骗人**
  （`xz: error reading stored compressor options` 是**无害警告**，
  官方健康镜像也报；真正的坏是 `xz uncompress failed with error code N`）

### ③ 华为 Q2S —— 同样先看有没有明文

```bash
strings -a flash.bin | grep -iE 'aes_string|hex:' | head
# 找到形如  hex:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX  的就是那把钥匙
# 然后：./hwkey 备份.conf verify 'hex:那把钥匙'     ← 一秒验证
```

也可以在 dump 里直接搜 rootfs / 配置分区找 `/etc/wap/aes_string` 的原文。

## 五、⚠️ 不要做的事

- **不要在没备份的情况下往 flash 里写任何东西**。CH341A 写 flash 比读危险得多
  （电压、时序、部分写入都可能把 u-boot 写坏 → 设备变砖）。
  先只读、只分析；确有必要再谈写，而且要先确认你**能恢复**。
- **不要带电夹**。设备必须完全断电，否则可能烧芯片或烧编程器。
- **不要把 dump 提交到公开仓库**。里面有厂商的密钥、你设备的凭据、
  可能还有射频校准数据 —— `.gitignore` 已排除 `*.bin`，但你自己也要注意。

## 六、如果觉得麻烦

那就**保持现状**。目前的状态是：**你需要的东西大部分已经拿到了** ——

- NETGEAR：配置全解、所有哈希全破、安全问题的语义也查清了
- Singtel：glbcfg 明文可读、密码派生规则完整（root/SSH 密码能算、管理密码能读）、
  登录算法源码级确认、同厂设备 rootfs 全解
- 华为：格式完全破译（本仓库已把它修正到与权威源码一致），只差那一把钥匙

**没拿到的三条，都是"信息不存在于手上"，而不是"方法不对"。**
拿到 flash dump 就是补上那块信息，不是重新开始。
