#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
routercfg —— 家用路由器配置备份的【统一识别 + 解码】工具

支持的四种格式（都是实测过的）：

  ① NETGEAR .cfg        ★ 完全可解。XOR + uClibc/musl 的 rand()，种子写在文件头里
  ② 华为 .conf          格式完全破译（aescrypt2）；★ 密钥在设备的 /etc/wap/aes_string。
                        老光猫全网共用一把，消费级机型一机一密 —— 文件本身解不开。
                        本工具带 **HMAC 密钥验证器**（256 位判据，零误判）
  ③ Arcadyan .trx       容器是普通 TRX（otrx，无加密）；WE410443-ST rootfs为两层byte变换+XZ，
                        可用 extender_rootfs.py 从提取出的 squashfs 完整解码
  ④ Arcadyan glbcfg     ★ 纯明文 key=value（管理密码/WiFi 口令都在里面，不用解密）
  ⑤ NETGEAR 官方固件    容器明文，rootfs 是普通 squashfs，能直接解（--extract）

用法:
    python3 routercfg.py 某个备份文件                    # 自动识别并尽可能解
    python3 routercfg.py --hw-test-key 'hex:xxxx' f      # 用 HMAC 判定华为密钥对不对
    python3 routercfg.py --info f                        # 只看格式，不动它
"""
import argparse
import gzip
import hashlib
import re
import struct
import sys
import tempfile
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════
# ① NETGEAR：XOR + rand()，种子 = 文件头的 magic
# ══════════════════════════════════════════════════════════════════════
NG_HEADER = 12
NG_CHUNK = 4
NG_INIT_CRC = 0xFFFFFFFF
NG_KNOWN_MAGICS = (0x20131224, 0x23091293, 0x01346232, 0x20200426)

_UC_RANDTBL = [-1726662223, 379960547, 1735697613, 1040273694, 1313901226, 1627687941,
               -179304937, -2073333483, 1780058412, -1989503057, -615974602, 344556628,
               939512070, -1249116260, 1507946756, -812545463, 154635395, 1388815473,
               -1926676823, 525320961, -1009028674, 968117788, -123449607, 1284210865,
               435012392, -2017506339, -911064859, -370259173, 1132637927, 1398500161,
               -205601318]


def _i32(x):
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x >= 0x80000000 else x


class RngUclibc:
    """uClibc 的 TYPE_3 rand()（randtbl + Lehmer LCG）"""

    def __init__(self, seed):
        st = list(_UC_RANDTBL)
        n = 31
        w = seed or 1
        st[0] = _i32(w)
        for i in range(1, n):
            hi, lo = w // 127773, w % 127773
            w = 16807 * lo - 2836 * hi
            if w < 0:
                w += 2147483647
            st[i] = _i32(w)
        self.f, self.r, self.st = 3, 0, st
        for _ in range(n * 10):
            self.rand()

    def rand(self):
        v = self.st[self.f] + self.st[self.r]
        self.st[self.f] = _i32(v)
        res = (v >> 1) & 0x7FFFFFFF
        self.f += 1
        if self.f >= 31:
            self.f, self.r = 0, self.r + 1
        else:
            self.r += 1
            if self.r >= 31:
                self.r = 0
        return res


class RngMusl:
    """musl 的 rand()（64 位 LCG）"""

    def __init__(self, seed):
        self.s = (seed - 1) & 0xFFFFFFFFFFFFFFFF

    def rand(self):
        self.s = (6364136223846793005 * self.s + 1) & 0xFFFFFFFFFFFFFFFF
        return _i32(self.s >> 33)


def netgear_decrypt(data, magic=None, rng=None):
    """返回 (明文, 元信息) 或 (None, 元信息)"""
    hdr = struct.unpack("<III", data[:NG_HEADER])
    stated, length, crc = hdr
    info = {"magic_stated": stated, "len": length, "crc": crc}
    magic = magic if magic is not None else stated
    body = data[NG_HEADER:NG_HEADER + length]
    rngs = [("musl", RngMusl), ("uclibc", RngUclibc)]
    if rng:
        rngs = [r for r in rngs if r[0] == rng]
    for name, cls in rngs:
        g = cls(magic)
        out = bytearray()
        for i in range(0, len(body) // NG_CHUNK * NG_CHUNK, NG_CHUNK):
            v = struct.unpack("<I", body[i:i + NG_CHUNK])[0] ^ (g.rand() & 0xFFFFFFFF)
            out += struct.pack("<I", v)
        c = crc
        for i in range(0, len(out) // NG_CHUNK * NG_CHUNK, NG_CHUNK):
            c = (c + struct.unpack("<I", out[i:i + NG_CHUNK])[0]) & 0xFFFFFFFF
        if c == NG_INIT_CRC:
            info.update(rng=name, magic_used=magic)
            return bytes(out), info
    info.update(rng=None)
    return None, info


def netgear_fields(plain):
    """解密后的格式是 key=value，记录之间用 \\x00 分隔"""
    out = {}
    for rec in plain.split(b"\x00"):
        if b"=" in rec:
            k, _, v = rec.partition(b"=")
            out[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace").strip()
    return out


# ★ 各字段用哪种哈希（实测钉死，别用错模式）
NG_HASH_HINT = {
    "http_passwd": "SHA256(明文)",
    "http_passwd_digest": "SHA256(明文)",
    "dhx2_passwd": "MD5-crypt（-m 500）",
    "samba_passwd": "★ NTLM = MD4(UTF-16LE) ——【不是 MD5】（-m 1000）",
    "PWD_answer1": "SHA256(答案)",
    "PWD_answer2": "SHA256(答案)",
    "wl_wpa2_psk": "明文", "wla_wpa2_psk": "明文",
}

NG_INTERESTING = [
    "http_username", "http_passwd", "http_passwd_digest",
    "wl_ssid", "wla_ssid", "wl_wpa2_psk", "wla_wpa2_psk",
    "wl_channel", "wla_channel", "wl_htmode", "wla_htmode",
    "lan_factory_mac", "wan_factory_mac", "cur_wanmac",
    "wan_pppoe_username", "wan_pppoe_passwd",
    "samba_passwd", "dhx2_passwd", "email_password",
    "PWD_question1", "PWD_answer1", "PWD_question2", "PWD_answer2",
    "enable_password_recovery", "endis_ssid_broadcast",
]


# ══════════════════════════════════════════════════════════════════════
# ② 华为：aescrypt2（★ 2026-10-16 按 palmerc/AESCrypt2 源码更正）
# ══════════════════════════════════════════════════════════════════════
HW_HEADER = 32          # 设备额外加的头
HW_TAG = 32             # 密文末尾的 HMAC-SHA256
HW_ONTSHARED_KEY = b"hex:13395537D2730554A176799F6D56A239"   # 老光猫全网共用

HW_MODEL_LINE = (
    "  结构 = [设备头 %d 字节][16 字节 IV][AES-256 密文（CBC 链式）][32 字节 HMAC-SHA256]\n"
    "  ★ 密钥派生: digest = IV ‖ 16 个零字节（共 32），迭代 8192 次 sha256(digest ‖ 密钥串)\n"
    "  ★ 分组模式: **CBC 链式**（IV 每块后更新为当前密文块）—— 不是独立逐块\n"
    "  ⚠ 密钥在设备的 /etc/wap/aes_string，【不在备份文件里】\n"
    "     老光猫(HG 系列)全网共用: %s\n"
    "     消费级(Q2S / WS5281 等)是一机一密，实测【不是上面那把】\n"
    "  用 --hw-test-key 可以验一把密钥对不对（HMAC 判据，零误判）"
) % (HW_HEADER, HW_ONTSHARED_KEY.decode())


def hw_derive_key(iv16, key):
    """★ 关键：digest 是 32 字节 = IV 后面补 16 个零"""
    if isinstance(key, str):
        key = key.encode()
    d = bytes(iv16) + b"\x00" * 16
    for _ in range(8192):
        d = hashlib.sha256(d + key).digest()
    return d


def hw_decrypt(data, key, hdr=HW_HEADER, tag=HW_TAG):
    """返回 (明文 或 None, 说明)。tag=0 表示文件没有 HMAC 尾巴。"""
    if hdr + 16 + tag + 16 > len(data):
        return None, "文件太短"
    iv = data[hdr:hdr + 16]
    ct = data[hdr + 16: len(data) - tag] if tag else data[hdr + 16:]
    k = hw_derive_key(iv, key)
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        return None, "需要 python3-cryptography（或用 --aescrypt2 走外部二进制）"
    pt = Cipher(algorithms.AES(k), modes.CBC(iv)).decryptor().update(ct)
    lastn = iv[15] & 0x0F
    if lastn and len(pt) >= 16:
        pt = pt[:-16] + pt[-16:][:lastn]
    return pt, "ok"


def hw_verify_hmac(data, key, hdr=HW_HEADER, tag=HW_TAG):
    """★ 256 位判据：验密文末尾的 HMAC。返回 True/False/None（文件没有 HMAC 就 None）"""
    if not tag or hdr + 16 + tag > len(data):
        return None
    iv = data[hdr:hdr + 16]
    ct = data[hdr + 16: len(data) - tag]
    want = data[len(data) - tag:]
    k = hw_derive_key(iv, key)
    ipad = bytearray(b"\x36" * 64)
    opad = bytearray(b"\x5c" * 64)
    for i in range(32):
        ipad[i] ^= k[i]
        opad[i] ^= k[i]
    inner = hashlib.sha256(bytes(ipad) + ct).digest()
    got = hashlib.sha256(bytes(opad) + inner).digest()
    return got == want


def hw_report(data, key=None):
    print("── 华为配置（aescrypt2）──")
    print(HW_MODEL_LINE)
    if key:
        ok = hw_verify_hmac(data, key)
        print("\n   试密钥 %r ..." % key)
        if ok is True:
            print("   ★★★ HMAC 通过 —— 密钥正确！")
        elif ok is False:
            print("   ✗ HMAC 不通过 —— 密钥不对")
        else:
            print("   （该文件尾部没有 32 字节 HMAC，只能用明文判据）")
        pt, why = hw_decrypt(data, key)
        if pt:
            good = pt[:2] == b"\x1f\x8b" or pt.lstrip()[:1] == b"<"
            print("   解密 %d 字节，%s" % (len(pt), "看起来是 gzip/XML" if good else
                                          "开头是 %s（不像明文）" % pt[:8].hex()))
            if pt[:2] == b"\x1f\x8b":
                try:
                    xml = gzip.GzipFile(fileobj=__import__("io").BytesIO(pt)).read()
                    print("   ★ gunzip 成功，%d 字节 XML" % len(xml))
                    return xml
                except Exception as e:
                    print("   gunzip 失败: %s" % e)
        elif why != "ok":
            print("   %s" % why)


# ══════════════════════════════════════════════════════════════════════
# ③ Arcadyan .trx（Singtel Mesh 等）
# ══════════════════════════════════════════════════════════════════════
# 文件里的字节是 5d 43 6f 74；小端读作 uint32 就是 0x746F435D
# （OpenWrt 的 mt7621.mk 里写的 `arcadyan-trx 0x746f435d` 正是这个值）
TRX_MAGIC = 0x746F435D
SQSH_MAGIC = b"hsqs"
UIMAGE_MAGIC = 0x27051956

# squashfs 标志位（★ 别记错：bit15 SET = 未压缩）
SQ_COMP_OPT = 0x0400

SINGTEL_NOTE = (
    "  容器 = 普通 TRX（OpenWrt 的 otrx 生成，源码里【没有任何加密】）\n"
    "  头 = magic(4) len(4) crc32(4) flag(4) off1(4) off2(4) off3(4)\n"
    "  kernel  = LZMA，非标准参数 lc=1/lp=2/pb=2 + dict 8MB → FORMAT_ALONE 直接解\n"
    "  rootfs  = WE410443-ST使用固定byte变换包裹XZ；超块/comp_opts明文\n"
    "            已完整提取，无需flash AES key；使用 extender_rootfs.py\n"
    "            证据见 docs/singtel-extender-crypto-path.md\n"
    "  ⚠ 判断加密要看【能不能解】，别靠熵（压缩数据熵也是 8.0）\n"
    "  ⚠ 有些镜像里 `hsqs` 是脚本 echo 进去的【假标记】，后面全是 0"
)


def trx_parse(data):
    magic, length, crc, flag = struct.unpack("<IIII", data[:16])
    off1, off2, off3 = struct.unpack("<III", data[16:28])
    return {"magic": magic, "len": length, "crc": crc, "flag": flag,
            "off1": off1, "off2": off2, "off3": off3}


def sqsh_super(data, off):
    """解析 squashfs 超块（4.0 格式，96 字节）"""
    if data[off:off + 4] != SQSH_MAGIC:
        return None
    (magic, inodes, mtime, bs, frags, comp, blog,
     flags, idc, vmaj, vmin) = struct.unpack("<IIIIIHHHHHH", data[off:off + 32])
    names = ["root_inode", "bytes_used", "id_tbl", "xattr_id_tbl",
             "inode_tbl", "dir_tbl", "frag_tbl", "lookup_tbl"]
    vals = dict(zip(names, struct.unpack("<QQQQQQQQ", data[off + 32:off + 96])))
    return {"inodes": inodes, "block_size": bs, "frags": frags, "comp": comp,
            "flags": flags, "ids": idc, "ver": "%d.%d" % (vmaj, vmin), **vals}


COMP_NAME = {1: "gzip", 2: "lzma", 3: "lzo", 4: "xz", 5: "lz4", 6: "zstd",
             7: "lz4hc", 8: "zstd"}


def trx_report(data, out_prefix):
    h = trx_parse(data)
    print("   magic=0x%08X len=%d crc=0x%08X flag=0x%X" %
          (h["magic"], h["len"], h["crc"], h["flag"]))
    print("   kernel@0x%X  rootfs@0x%X  off3@0x%X" % (h["off1"], h["off2"], h["off3"]))
    # kernel
    if data[h["off1"]:h["off1"] + 4] == struct.pack(">I", UIMAGE_MAGIC):
        size = struct.unpack(">I", data[h["off1"] + 12:h["off1"] + 16])[0]
        body = data[h["off1"] + 64:h["off1"] + 64 + size]
        print("   uImage: size=%d comp=%d" % (size, data[h["off1"] + 31]))
        try:
            import lzma
            k = lzma.decompress(body, format=lzma.FORMAT_ALONE)
            out = Path(str(out_prefix) + ".kernel")
            out.write_bytes(k)
            print("   ★ kernel 解出来了（%d 字节）→ %s" % (len(k), out))
        except Exception as e:
            print("   kernel 解压失败: %s" % str(e)[:60])
    # rootfs：超块应是明文，其后应解不开
    off = h["off2"]
    sb = sqsh_super(data, off)
    if sb:
        print("   ★ rootfs 超块 = 明文（合法）：")
        print("       inodes=%d block=%d frags=%d comp=%d(%s) flags=0x%04x ver=%s"
              % (sb["inodes"], sb["block_size"], sb["frags"], sb["comp"],
                 COMP_NAME.get(sb["comp"], "?"), sb["flags"], sb["ver"]))
        print("       bytes_used=%d  inode_tbl=0x%X  dir_tbl=0x%X"
              % (sb["bytes_used"], sb["inode_tbl"], sb["dir_tbl"]))
        if sb["flags"] & SQ_COMP_OPT:
            print("       flags 含 COMP_OPT(0x0400) → 超块后紧跟 comp_opts 块")
        # 超块之后的第一个块：明文还是密文？
        after = data[off + 96:off + 96 + 16]
        print("       超块后首块: %s  ← 若读不出压缩器选项即为【密文】" % after.hex())
    elif data[off:off + 4] == SQSH_MAGIC:
        print("   rootfs: 那 4 字节 hsqs 是【假标记】（后面全 0）")
    print()
    print(SINGTEL_NOTE)


# ══════════════════════════════════════════════════════════════════════
# ④ Arcadyan glbcfg —— ★ 纯明文，直接能用
# ══════════════════════════════════════════════════════════════════════
ARC_SECRET_KEYS = [
    "ARC_SYS_Password", "ARC_ROOT_Passwd", "ARC_SYS_LoginBlocked",
    "ARC_SYS_SerialNum", "ARC_SYS_IsFactoryDefault",
    "ARC_UI_WEB_REMOTEMN_Password", "ARC_UI_WEB_REMOTEMN_Enable",
    "ARC_TR69_Password", "ARC_TR69_Username", "ARC_TR69_URL",
    "ARC_IPSEC_0_PSK_KEY", "ARC_DDNS_0_Password",
    "ARC_WLAN_24G_SSID_0_ESSID", "ARC_WLAN_5G_SSID_0_ESSID",
    "ARC_WLAN_24G_SSID_0_WPA_Passphrase", "ARC_WLAN_5G_SSID_0_WPA_Passphrase",
    "ARC_WLAN_24G_SSID_0_WPA_GroupRekey", "ARC_WLAN_24G_SSID_0_WPS_ExRegistrarPIN",
    "ARC_WAN_000_PPP_Username", "ARC_WAN_000_PPP_Password",
]

ARC_NOTE = (
    "  ★ glbcfg 是【纯明文】的 key=value（2480 行左右），不需要任何解密。\n"
    "     设备上的 glbcfg(0x1fb0000) / config(0x1fc0000) 分区同理 ——\n"
    "     **管理密码、WiFi 口令都是明文躺在里面**，SPI 读出来即可。\n"
    "  密码怎么来的（见 /sbin/arc_glbcfg 脚本）：\n"
    "     root/SSH 密码 = 's1ngt3l' + 序列号后 6 位   ← ★ 可离线算\n"
    "     ARC_ROOT_Passwd = MD5(上面那个)              ← ★ 可离线算\n"
    "     ARC_UI_WEB_REMOTEMN_Password = MD5(序列号)   ← ★ 可离线算\n"
    "     ARC_SYS_Password(管理界面) = arc_board get gui-pwd   ← 板级出厂数据\n"
    "     WiFi 口令 / WPS PIN = arc_board get wifi-*-pwd / wps-pin\n"
    "     板级数据在 /dev/brcmboard"
)


def arc_fields(text):
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


# ══════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════
# ⑤ NETGEAR 官方固件（.img / CHK）—— 容器明文，rootfs 是标准 squashfs
# ══════════════════════════════════════════════════════════════════════
# 结构（实测 R7800-V1.0.2.90.img）：
#   0x0        文本头   device:R7800 / version:V1.0.2.90 / region: / hd_id:...
#   0x80       uImage   内核
#   0x220040   第二个 uImage
#   0x220080   ★ squashfs 超块（明文、合法）
#   0x666CFD   "CHK" 标记
NETGEAR_FW_HDR = b"device:"

NG_FW_NOTE = (
    "  容器【不加密】，rootfs 是普通 squashfs（xz）—— 可直接 unsquashfs 解开。\n"
    "  ⚠ `unsquashfs` 会报一句\n"
    "      xz: error reading stored compressor options from filesystem!\n"
    "    ★ 那只是【无害警告】：官方健康镜像也报这句，但照样能解出全部文件。\n"
    "    别拿它当\"文件系统坏了/被加密了\"的依据（真正的坏是\n"
    "      xz uncompress failed with error code N + FATAL ERROR: File system corruption）。\n"
    "  对照：同一台设备上 NETGEAR 的\"安全分区\"用的是 cryptsetup LUKS\n"
    "  （lib/libntgrcrypt.so 里有 luksformat/luksopen），是真加密；\n"
    "  但【配置备份】只用了 rand() XOR（见 docs/netgear-config-decrypt.md）。\n"
    "  ⇒ \"备份能解\"不等于\"这台设备别的也能解\"，要分清在哪一层。"
)


def ng_fw_scan(data):
    """在固件里找一个合法的 squashfs 超块"""
    out = []
    start = 0
    while True:
        i = data.find(SQSH_MAGIC, start)
        if i < 0:
            break
        sb = sqsh_super(data, i)
        if sb and 0 < sb["inodes"] < 100000 and sb["block_size"] >= 4096:
            out.append((i, sb))
        start = i + 1
    return out


def ng_fw_report(data, out_prefix, do_extract=False):
    print("── NETGEAR 官方固件（.img / CHK）──")
    # 文本头
    end = data.find(b"\x00", 0)
    head = data[:end if 0 < end < 1024 else 512]
    try:
        txt = head.decode("ascii")
        if txt.startswith("device:"):
            print("   文本头:")
            for line in txt.splitlines()[:6]:
                print("      %s" % line)
    except UnicodeDecodeError:
        pass
    # uImage
    for m in re.finditer(re.escape(struct.pack(">I", UIMAGE_MAGIC)), data[:0x300000]):
        o = m.start()
        name = data[o + 32:o + 64].split(b"\x00")[0]
        size = struct.unpack(">I", data[o + 12:o + 16])[0]
        print("   uImage @ 0x%-8X name=%-18s size=%d comp=%d"
              % (o, name.decode("latin1"), size, data[o + 31]))
    # CHK
    c = data.find(b"CHK")
    if c > 0:
        print("   CHK 标记 @ 0x%X" % c)
    # squashfs
    sq = ng_fw_scan(data)
    if not sq:
        print("   ✗ 没找到合法 squashfs 超块")
        return 1
    for off, sb in sq:
        print("   ★ squashfs @ 0x%X" % off)
        print("       inodes=%d block=%d frags=%d comp=%d(%s) flags=0x%04x ver=%s"
              % (sb["inodes"], sb["block_size"], sb["frags"], sb["comp"],
                 COMP_NAME.get(sb["comp"], "?"), sb["flags"], sb["ver"]))
        print("       bytes_used=%d" % sb["bytes_used"])
    off, sb = sq[0]
    out = Path(str(out_prefix) + ".rootfs.sqsh")
    out.write_bytes(data[off:off + sb["bytes_used"]])
    print("   → 已切出 %s（%d 字节）" % (out, sb["bytes_used"]))
    print()
    print(NG_FW_NOTE)
    if do_extract:
        import subprocess
        d = Path(str(out_prefix) + ".rootfs")
        print("\n   解压到 %s ..." % d)
        r = subprocess.run(["unsquashfs", "-d", str(d), str(out)],
                           capture_output=True, text=True)
        tail = [l for l in (r.stdout or "").splitlines() if l.startswith(("created", "FATAL"))]
        for l in tail[:6]:
            print("     %s" % l)
    else:
        print("\n   解压: unsquashfs -d <目录> %s" % out)
    return 0


def identify(data):
    # ★ NETGEAR 官方固件：文本头 device:... + 内含合法 squashfs
    if data[:len(NETGEAR_FW_HDR)] == NETGEAR_FW_HDR:
        return "ng_firmware"
    if len(data) >= 36 and data[0:4] == b"\x00\x00\x00\x02":
        return "huawei"
    if len(data) > 24 and struct.unpack("<I", data[:4])[0] == TRX_MAGIC:
        return "trx"
    # Arcadyan glbcfg / 明文 key=value
    head = data[:4096]
    if b"ARC_" in head and b"=" in head:
        try:
            head.decode("ascii")
            if head.count(b"\n") > 8:
                return "arc_glbcfg"
        except UnicodeDecodeError:
            pass
    if len(data) > 12:
        magic = struct.unpack("<I", data[:4])[0]
        if magic in NG_KNOWN_MAGICS or (data[4:8] and 100 < struct.unpack("<I", data[4:8])[0] < len(data) + 16):
            ln = struct.unpack("<I", data[4:8])[0]
            if abs(ln - (len(data) - 12)) <= 16:
                return "netgear"
    return "unknown"


def main():
    ap = argparse.ArgumentParser(description="家用路由器配置备份统一解码")
    ap.add_argument("file")
    ap.add_argument("--info", action="store_true", help="只识别格式，不尝试解")
    ap.add_argument("--huawei-key", "--hw-test-key", dest="hw_key",
                    help="华为配置的密钥串（如 hex:....），会用 HMAC 判据验证")
    ap.add_argument("--hw-hdr", type=int, default=HW_HEADER, help="华为设备的头长度（默认 32）")
    ap.add_argument("--hw-tag", type=int, default=HW_TAG, help="华为末尾 HMAC 长度（默认 32，没有就填 0）")
    ap.add_argument("-o", "--out", help="输出文件前缀")
    ap.add_argument("--extract", action="store_true",
                    help="NETGEAR 固件：顺便用 unsquashfs 把 rootfs 解出来")
    a = ap.parse_args()

    p = Path(a.file)
    data = p.read_bytes()
    kind = identify(data)
    print("文件  : %s (%d 字节)" % (p, len(data)))
    print("格式  : %s" % kind)
    print()
    if a.info:
        return 0

    if kind == "netgear":
        print("── NETGEAR 配置（XOR + rand()，种子在文件头）──")
        plain, info = netgear_decrypt(data)
        print("   magic=0x%08X  len=%d  crc=0x%08X  rng=%s"
              % (info["magic_stated"], info["len"], info["crc"], info.get("rng")))
        if not plain:
            print("  ✗ 校验没过 —— 两个 RNG 都试了。可能是别的 magic")
            return 1
        fields = netgear_fields(plain)
        print("  ★ 解密成功，%d 个配置项" % len(fields))
        print()
        for k in NG_INTERESTING:
            if fields.get(k):
                print("   %-24s = %s" % (k, fields[k][:60]))
        print("\n  ── 这些字段该用哪种哈希 ──")
        for k, v in NG_HASH_HINT.items():
            print("   %-24s %s" % (k, v))
        out = Path(a.out or (str(p) + ".dec"))
        out.write_bytes(plain)
        print("\n  完整明文 → %s" % out)
        return 0

    if kind == "ng_firmware":
        return ng_fw_report(data, a.out or p, do_extract=a.extract)

    if kind == "huawei":
        if a.hw_key:
            xml = hw_report(data, a.hw_key)
            if xml:
                out = Path(a.out or (str(p) + ".xml"))
                out.write_bytes(xml)
                print("   → %s" % out)
                return 0
            return 1
        hw_report(data, None)
        return 1

    if kind == "trx":
        trx_report(data, a.out or p)
        return 1

    if kind == "arc_glbcfg":
        print("── Arcadyan glbcfg（★ 明文，不用解密）──")
        print(ARC_NOTE)
        print()
        fields = arc_fields(data.decode("utf-8", "replace"))
        print("  共 %d 个配置项。关注这些：" % len(fields))
        for k in ARC_SECRET_KEYS:
            if fields.get(k):
                print("   %-44s = %s" % (k, fields[k][:60]))
        return 0

    print("  认不出来。可以告诉我是哪台设备，我加上识别规则。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
