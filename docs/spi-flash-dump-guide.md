# SPI Flash 读取与备份指南

**2026-10-24 更正：** extender rootfs 已可从固件完整提取，不需要SPI key。
旧版“三个目标卡在同一块SPI flash”的说法也不成立：华为Q2S与Singtel是不同设备。
华为配置key、原始bootloader备份等仍可能需要各自设备的flash材料。
见[extender解码证据](singtel-extender-crypto-path.md)。

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

## 四、拿到 dump 之后怎么用

### 先跑一遍自动分析工具（`flashdump.py`）

```bash
python3 flashdump.py flash-original.bin --out 提取/
```

它会按**性价比顺序**把该看的都标出来：① 明文配置块（含口令字段，**这个最可能直接给你答案**）
② 华为 keystring ③ AES 表位置（密钥通常在附近）④ 文件系统/容器 ⑤ 分区表对照。
**找到了就照它给的下一步做；下面几节是手动深挖时的补充。**

### 手动深挖（按性价比排序）

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

### ② Extender rootfs 已不需要 flash key（2026-10-24 更正）

旧版AES-ECB推断与“只剩flash key”结论已被真实kernel路径推翻。
`get_decrypt_keys` 原定位是字符串，实际算法为两层固定byte变换包裹XZ。
现在使用 `extender_rootfs.py` 即可离线提取；证据见
[extender crypto路径](singtel-extender-crypto-path.md)。`arckey.c` 保留为通用候选验证工具，
不再作为本extender的解码方法。SPI dump仍可用于备份和研究bootloader。

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
