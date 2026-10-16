#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
routercfg —— 家用路由器配置备份的【统一识别 + 解码】工具

支持的三种格式（都是实测过的）：

  ① NETGEAR .cfg     ★ 完全可解。XOR + uClibc/musl 的 rand()，种子写在文件头里
  ② 华为 .conf       格式已破译（aescrypt2: 头32 + IV16 + AES-256），
                     但密钥在设备的 /etc/wap/aes_string —— 文件本身解不开
  ③ Arcadyan .trx    容器是普通 TRX（otrx，无加密）；但 rootfs 是 Arcadyan 自家 AES，
                     密钥在 bootloader —— 只有 kernel 能取出来

用法:
    python3 routercfg.py 某个备份文件            # 自动识别并尽可能解
    python3 routercfg.py --huawei-key <密钥串> f # 手动给华为那把钥匙
    python3 routercfg.py --info f                # 只看格式，不动它
"""
import argparse
import gzip
import hashlib
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════
# ① NETGEAR：XOR + rand()，种子 = 文件头的 magic
# ══════════════════════════════════════════════════════════════════════
NG_HEADER = 12
NG_CHUNK = 4
NG_INIT_CRC = 0xFFFFFFFF
# 老固件常用的种子（头里的 magic 就是这个）
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
# ② 华为：aescrypt2（头32 + IV16 + AES-256）
# ══════════════════════════════════════════════════════════════════════
HW_HEADER = 32
HW_ONTSHARED_KEY = "hex:13395537D2730554A176799F6D56A239"   # 老光猫全网共用
HW_AESCRYPT2_SRC = "https://github.com/palmerc/AESCrypt2"

HW_MODEL_LINE = (
    "  结构 = [设备头 %d 字节][16 字节 IV][AES-256 密文]\n"
    "  密钥 = SHA256(IV ‖ 密钥串) 迭代 8192 次；每块先 XOR IV 再 AES\n"
    "  ⚠ 密钥在设备的 /etc/wap/aes_string，【不在备份文件里】\n"
    "     老光猫共用: %s\n"
    "     消费级(Q2S 等)不是这把。要拿设备的密钥只能有 shell 或固件。\n"
    "  参考实现: %s"
) % (HW_HEADER, HW_ONTSHARED_KEY, HW_AESCRYPT2_SRC)


def huawei_try(data, key, aescrypt2=None):
    """用 aescrypt2 解，看能不能 gunzip 出来"""
    if not aescrypt2 or not Path(aescrypt2).exists():
        return None
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "b.bin").write_bytes(data[HW_HEADER:])
        (d / "k.txt").write_text(key)
        r = subprocess.run([aescrypt2, "1", str(d / "b.bin"), str(d / "o.bin"), str(d / "k.txt")],
                           capture_output=True)
        if r.returncode != 0 or not (d / "o.bin").exists():
            return None
        out = (d / "o.bin").read_bytes()
        if out[:2] != b"\x1f\x8b":
            return None
        try:
            return gzip.decompress(out)
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════
# ③ Arcadyan .trx（Singtel Mesh 等）
# ══════════════════════════════════════════════════════════════════════
# 文件里的字节是 5d 43 6f 74；小端读作 uint32 就是 0x746F435D
# （OpenWrt 的 mt7621.mk 里写的 `arcadyan-trx 0x746f435d` 正是这个值）
TRX_MAGIC = 0x746F435D
SQSH_MAGIC = b"hsqs"
UIMAGE_MAGIC = 0x27051956

SINGTEL_NOTE = (
    "  容器 = 普通 TRX（OpenWrt 的 otrx 生成，源码里【没有任何加密】）\n"
    "  头 = magic(4) len(4) crc32(4) flag(4) off1(4) off2(4) off3(4)\n"
    "  kernel  = LZMA，非标准参数 lc=1/lp=2/pb=2 + dict 8MB → FORMAT_ALONE 直接解\n"
    "  rootfs  = ★ Arcadyan 自家 AES 加密（不是容器干的）\n"
    "            5616 种压缩参数组合全失败、0 个 xz 魔数、熵 7.999\n"
    "            密钥在 flash 的 u-boot(0x0) / u-boot-env(0x30000)，【不在固件包里】\n"
    "  ⚠ 有些镜像里 `hsqs` 是脚本 echo 进去的【假标记】，后面全是 0，别被它骗了"
)


def trx_parse(data):
    magic, length, crc, flag = struct.unpack("<IIII", data[:16])
    off1, off2, off3 = struct.unpack("<III", data[16:28])
    return {"magic": magic, "len": length, "crc": crc, "flag": flag,
            "off1": off1, "off2": off2, "off3": off3}


def _sqsh_valid(blob, off):
    if blob[off:off + 4] != SQSH_MAGIC:
        return False
    try:
        inodes, _t, bs, _fr, comp = struct.unpack("<IIIII", blob[off + 4:off + 24])
    except Exception:
        return False
    return 0 < inodes < 100000 and 4096 <= bs <= 1048576 and comp in (1, 2, 3, 4, 5, 6)


# ══════════════════════════════════════════════════════════════════════
def identify(data):
    if len(data) > 12:
        magic = struct.unpack("<I", data[:4])[0]
        if magic in NG_KNOWN_MAGICS or (data[4:8] and 100 < struct.unpack("<I", data[4:8])[0] < len(data) + 16):
            # NETGEAR 的头 = magic/len/crc，len 应该约等于文件大小
            ln = struct.unpack("<I", data[4:8])[0]
            if abs(ln - (len(data) - 12)) <= 16:
                return "netgear"
    if struct.unpack("<I", data[:4])[0] == TRX_MAGIC:
        return "trx"
    if len(data) >= 36 and data[0:4] == b"\x00\x00\x00\x02":
        return "huawei"
    return "unknown"


def main():
    ap = argparse.ArgumentParser(description="家用路由器配置备份统一解码")
    ap.add_argument("file")
    ap.add_argument("--info", action="store_true", help="只识别格式，不尝试解")
    ap.add_argument("--huawei-key", help="华为配置的密钥串（如 hex:....）")
    ap.add_argument("--aescrypt2", default="./aescrypt2", help="aescrypt2 可执行文件路径")
    ap.add_argument("-o", "--out", help="输出文件前缀")
    a = ap.parse_args()

    p = Path(a.file)
    data = p.read_bytes()
    kind = identify(data)
    print("文件  : %s (%d 字节)" % (p, len(data)))
    print("格式  : %s" % kind)
    print()

    if kind == "netgear":
        print("── NETGEAR 配置（XOR + rand()，种子在文件头）──")
        plain, info = netgear_decrypt(data)
        print("   magic=0x%08X  len=%d  crc=0x%08X  rng=%s"
              % (info["magic_stated"], info["len"], info["crc"], info.get("rng")))
        if not plain:
            print("  ✗ 校验没过 —— 两个 RNG 都试了。可能是别的 magic，用 --magic 指定")
            return 1
        fields = netgear_fields(plain)
        print("  ★ 解密成功，%d 个配置项" % len(fields))
        print()
        for k in NG_INTERESTING:
            if fields.get(k):
                print("   %-24s = %s" % (k, fields[k][:70]))
        out = Path(a.out or (str(p) + ".dec"))
        out.write_bytes(plain)
        print("\n  完整明文 → %s" % out)
        return 0

    if kind == "huawei":
        print("── 华为配置（aescrypt2）──")
        print(HW_MODEL_LINE)
        keys = []
        if a.huawei_key:
            keys.append(a.huawei_key)
        keys.append(HW_ONTSHARED_KEY)
        for k in keys:
            print("\n   试密钥 %r ..." % k)
            pt = huawei_try(data, k, a.aescrypt2)
            if pt:
                print("   ★★★ 成功！%d 字节明文" % len(pt))
                out = Path(a.out or (str(p) + ".xml"))
                out.write_bytes(pt)
                print("   → %s" % out)
                return 0
            print("     不成（要么密钥不对，要么没编译 aescrypt2）")
        return 1

    if kind == "trx":
        print("── Arcadyan .trx（Singtel Mesh 等）──")
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
                out = Path(a.out or (str(p) + ".kernel"))
                out.write_bytes(k)
                print("   ★ kernel 解出来了（%d 字节）→ %s" % (len(k), out))
            except Exception as e:
                print("   kernel 解压失败: %s" % str(e)[:60])
        # rootfs
        off = h["off2"]
        if _sqsh_valid(data, off):
            print("   rootfs: 超块合法（明文），但数据段加密")
        elif data[off:off + 4] == SQSH_MAGIC:
            print("   rootfs: 那 4 字节 hsqs 是【假标记】（后面全 0）")
        print()
        print(SINGTEL_NOTE)
        return 1

    print("  认不出来。可以告诉我是哪台设备，我加上识别规则。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
