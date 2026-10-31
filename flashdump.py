#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flashdump —— SPI flash dump 自动分析（配合 docs/spi-flash-dump-guide.md 用）

拿到 flash dump 之后直接跑这个，它会按【性价比】顺序把该看的都标出来：

  ① 明文配置块    —— Arcadyan glbcfg / config 分区是明文，管理密码/口令直接就在里面
  ② 华为 keystring —— 形如 hex:<32位十六进制>，找到后用 hwkey 一秒验证
  ③ 加密实现特征   —— AES 正/逆 S 盒、Td0/Te0（定位 crypto 代码，密钥通常在附近）
  ④ 文件系统/容器  —— uImage / squashfs / UBI / JFFS2 / TRX
  ⑤ 分区提示       —— 按已知的 we410443 分区表，指出每个偏移应该是什么

用法:
    python3 flashdump.py dump.bin
    python3 flashdump.py dump.bin --out 提取目录     # 顺便把明文块切出来
"""
import argparse
import collections
import math
import re
import struct
import sys
from pathlib import Path

# ── 已知分区表（Singtel/Arcadyan WE410443-ST，32MB NOR；来自 we410443.dts）──
PARTITIONS = [
    (0x000000, 0x030000, "u-boot",     "bootloader；本extender rootfs解码不需要其key"),
    (0x030000, 0x010000, "u-boot-env", "bootloader环境；勿推断包含rootfs key"),
    (0x040000, 0x010000, "factory",    "射频校准"),
    (0x050000, 0x1F60000, "firmware",  "kernel + rootfs"),
    (0x1FB0000, 0x010000, "glbcfg",    "★ 明文配置（WiFi 口令）"),
    (0x1FC0000, 0x010000, "config",    "★★ 管理密码 ARC_SYS_Password（明文）"),
    (0x1FD0000, 0x010000, "glbcfg2",   "备份"),
    (0x1FE0000, 0x010000, "config2",   "备份"),
]

# ── 特征表 ──
AES_TABLES = {
    "AES 正 S 盒": bytes.fromhex("637c777bf26b6fcf3001672bfed7ab76"),
    "AES 逆 S 盒": bytes.fromhex("52096ad53036a538bf40a39e81f3d7fb"),
    "AES Te0(LE)": bytes.fromhex("a56363c6847c7c7f99ee7777"),
    "AES Td0(BE)": bytes.fromhex("51f4a7507e4165531a17a4c33a275e96"),
}
MAGICS = [
    (b"\x27\x05\x19\x56", "uImage 头"),
    (b"hsqs",             "squashfs 超块"),
    (b"UBI#",             "UBI EC 头"),
    (b"UBI!",             "UBI VID 头"),
    (b"\x85\x19",         "JFFS2 节点"),
    (b"\x19\x85",         "JFFS2 节点(另一种字节序)"),
    (b"5d436f74",         "TRX 容器(ASCII 写法)"),
    (b"\x1f\x8b\x08",     "gzip 流"),
    (b"\xfd7zXZ\x00",     "XZ 流"),
    (b"CHK",              "NETGEAR CHK"),
    (b"device:",          "NETGEAR 固件文本头"),
    (b"U-Boot",           "★ U-Boot 字符串！"),
    (b"bootdelay",        "★ U-Boot 环境变量！"),
    (b"bootcmd",          "★ U-Boot 环境变量！"),
]

# 配置里值得单独拎出来的字段
INTERESTING_KEYS = re.compile(
    r"^ARC_(SYS_Password|ROOT_Passwd|SYS_SerialNum|SYS_LoginBlocked|SYS_ModelName|"
    r"UI_WEB_REMOTEMN_Password|TR69_Password|TR69_Username|TR69_URL|"
    r"WLAN_24G_SSID_\d+_ESSID|WLAN_5G_SSID_\d+_ESSID|"
    r"WLAN_24G_SSID_\d+_WPA_Passphrase|WLAN_5G_SSID_\d+_WPA_Passphrase|"
    r"WLAN_\w+_WPS_ExRegistrarPIN|WAN_\d+_PPP_Username|WAN_\d+_PPP_Password|"
    r"IPSEC_\d+_PSK_KEY|DDNS_\d+_Password)$", re.I)


def entropy(b):
    if not b:
        return 0.0
    c = collections.Counter(b)
    n = len(b)
    return -sum(v / n * math.log2(v / n) for v in c.values())


def find_all(data, needle, limit=40):
    out, start = [], 0
    while len(out) < limit:
        i = data.find(needle, start)
        if i < 0:
            break
        out.append(i)
        start = i + 1
    return out


def scan_plaintext_config(data, min_run=64):
    """扫描明文 key=value 配置块。返回 [(偏移, 长度, {键:值})]"""
    blocks = []
    # 配置块的特征：连续的 ASCII key=value，行尾是 \n
    pat = re.compile(rb"(?:[A-Za-z_][A-Za-z0-9_]{2,40}=[^\n\x00]{0,120}\n){3,}")
    for m in pat.finditer(data):
        start, blob = m.start(), m.group()
        if len(blob) < min_run:
            continue
        fields = {}
        for line in blob.split(b"\n"):
            if b"=" in line:
                k, _, v = line.partition(b"=")
                k = k.strip().decode("ascii", "replace")
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]{2,40}$", k):
                    fields[k] = v.decode("utf-8", "replace").strip()
        if len(fields) >= 3:
            blocks.append((start, len(blob), fields))
    return blocks


def main():
    ap = argparse.ArgumentParser(description="SPI flash dump 自动分析")
    ap.add_argument("dump")
    ap.add_argument("--out", help="把明文配置块切出来放到这个目录")
    a = ap.parse_args()

    p = Path(a.dump)
    data = p.read_bytes()
    n = len(data)
    print("文件 : %s" % p)
    print("大小 : %d 字节 (%.1f MB)" % (n, n / 1048576))
    nz = next((i for i, b in enumerate(data) if b), None)
    print("首个非零字节: %s   整体熵: %.3f"
          % (hex(nz) if nz is not None else "无(全零)", entropy(data[:min(n, 4 << 20)])))
    print()

    # ── ⑤ 分区提示 ──
    print("════ 已知分区表对照（Singtel/Arcadyan 32MB NOR）════")
    if n < 0x2000000:
        print("  ⚠ 这份 dump 只有 %.1f MB，小于 32MB —— 可能是别的设备，下面的偏移仅供参考"
              % (n / 1048576))
    for off, size, name, note in PARTITIONS:
        mark = "  " if off + size <= n else " ✗"
        print("  %s 0x%07X  0x%06X  %-11s %s" % (mark, off, size, name, note))
    print()

    # ── ① 明文配置块（最高优先级）──
    print("════ ① 明文配置块（找到就等于直接拿到口令，不用破任何东西）════")
    blocks = scan_plaintext_config(data)
    if not blocks:
        print("  未找到 —— 这个设备的配置不是明文 key=value 形式")
    else:
        # ★ 关键：把【含敏感字段】的块全部列出来，不能只显示前几个
        #   （config 分区往往排在 glbcfg 几十个块之后，只显示前 10 个会正好漏掉它）
        interesting = [(o, l, f) for o, l, f in blocks
                       if any(INTERESTING_KEYS.match(k) for k in f)]
        print("  共找到 %d 个配置块，其中 %d 个含敏感字段" % (len(blocks), len(interesting)))
        for off, ln, fields in interesting:
            print("  ★ 0x%X 起，%d 字节，%d 个配置项" % (off, ln, len(fields)))
            for k, v in fields.items():
                if INTERESTING_KEYS.match(k):
                    print("      %-42s = %s" % (k, v[:60] if v else "(空)"))
        if not interesting:
            print("  （没有敏感字段命中，前 5 个块供参考）")
            for off, ln, fields in blocks[:5]:
                print("  0x%X 起，%d 字节，%d 个配置项；示例键: %s"
                      % (off, ln, len(fields), list(fields)[:3]))
    if a.out and blocks:
        od = Path(a.out)
        od.mkdir(parents=True, exist_ok=True)
        # 优先切出含敏感字段的块
        order = sorted(blocks, key=lambda b: -sum(
            1 for k in b[2] if INTERESTING_KEYS.match(k)))
        for off, ln, _f in order[:20]:
            (od / ("config_0x%X.bin" % off)).write_bytes(data[off:off + ln])
        print("  → 已切出 %d 个配置块到 %s（含敏感字段的排前面）"
              % (min(len(blocks), 20), od))
    print()

    # ── ② 华为 keystring ──
    print("════ ② 华为 keystring（形如 hex:<32位十六进制>）════")
    ks = set(re.findall(rb"hex:[0-9A-Fa-f]{16,64}", data))
    if ks:
        for k in list(ks)[:10]:
            print("  ★ %s      ← 用 ./hwkey 备份.conf verify '%s' 验证"
                  % (k.decode(), k.decode()))
    else:
        print("  未找到（这台设备可能不是华为）")
    print()

    # ── ③ 加密实现特征 ──
    print("════ ③ 加密实现特征（定位 crypto 代码，密钥通常在附近）════")
    any_hit = False
    for name, pat in AES_TABLES.items():
        locs = find_all(data, pat, 8)
        if locs:
            any_hit = True
            print("  ★ %-12s @ %s" % (name, [hex(x) for x in locs]))
    if not any_hit:
        print("  未找到常见 AES 表（可能是别家实现，或表被混淆了）")
    print()

    # ── ④ 文件系统/容器 ──
    print("════ ④ 文件系统与容器 ════")
    for pat, name in MAGICS:
        locs = find_all(data, pat, 8)
        if locs:
            print("  %-26s %s%s" % (name, [hex(x) for x in locs[:6]],
                                    "  ..." if len(locs) == 8 else ""))
    print()

    # ── 高熵区（可能是加密/压缩区）──
    print("════ 高熵区（可能是加密或压缩，按 1MB 粒度）════")
    step = 1 << 20
    runs = []
    for off in range(0, n, step):
        e = entropy(data[off:off + step])
        if e > 7.9:
            runs.append(off)
    if runs:
        # 合并连续段
        segs, s = [], runs[0]
        for x, y in zip(runs, runs[1:] + [None]):
            if y != (x + step):
                segs.append((s, x + step))
                s = y
        for s0, s1 in segs[:8]:
            print("  0x%07X ~ 0x%07X  (%.1f MB)" % (s0, s1, (s1 - s0) / 1048576))
    else:
        print("  无（整片熵都不高 → 可能没加密）")
    print()

    print("════ 下一步 ════")
    print("  1. 上面 ① 有命中 → 口令已经拿到了，任务结束")
    print("  2. ② 有命中 → ./hwkey <备份.conf> verify '<那把钥匙>'")
    print("  3. ③ 有命中 → 在那些偏移【前后几 KB】找 16/32 字节的高熵常量，")
    print("     拿它去解 rootfs（判据：解出来要出现合法魔数）")
    print("  4. 找不到就问：u-boot-env 有没有被当人话读过？")
    print("     strings -a -n 6 dump.bin | grep -iE 'key|aes|rootfs|pass'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
