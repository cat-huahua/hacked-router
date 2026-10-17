#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jffs2_extract —— 从裸镜像里提取 JFFS2 文件系统（自动判端序）

为什么单独写一个：常规工具遇到这两件事会直接失败，而它们看起来都像"数据被加密了"：

  ① 字段端序反了 —— 见到的镜像把 JFFS2 的字段按【小端】存（标准是大端）。
     症状：魔数扫描 find 不到、节点数 0。
  ② CRC 约定不同 —— JFFS2 用的是 Linux 内核的 crc32()，和 zlib 的差一次首尾取反。
     症状：字段都解对了，但 hdr_crc 一个都不过。

判据：用 magic + nodetype + totlen + hdr_crc 四者同时成立来【反推】正确端序，
      而不是靠猜。四者全对才算定死。

用法:
    python3 jffs2_extract.py 镜像.bin [-o 输出目录]
"""
import argparse
import collections
import pathlib
import re
import struct
import sys
import zlib


def jffs2_crc(data):
    """★ JFFS2 用的是 Linux 内核的 crc32()，不是 zlib 的约定。"""
    return (zlib.crc32(data, 0xFFFFFFFF) ^ 0xFFFFFFFF) & 0xFFFFFFFF


NTYPE = {0xE001: "DIRENT", 0xE002: "INODE", 0xE003: "CLEANMARKER"}
COMPR = {0: "none", 1: "zero", 2: "rtime", 3: "rubin", 4: "copy",
         5: "dynrubin", 6: "zlib", 7: "lzo", 8: "lzma"}


def scan_nodes(blob, endian):
    """按给定端序扫节点，返回 [(off, ntype, totlen, crc_ok)]"""
    n = len(blob)
    magic_pat = b"\x19\x85" if endian == ">" else b"\x85\x19"
    out, o = [], 0
    while o < n - 12:
        magic, ntype, totlen, hcrc = struct.unpack(endian + "HHII", blob[o:o+12])
        if magic == 0x1985 and 8 <= totlen <= 0x20000 and o + totlen <= n:
            out.append((o, ntype, totlen, jffs2_crc(blob[o:o+8]) == hcrc))
            o += (totlen + 3) & ~3
        else:
            nx = blob.find(magic_pat, o + 1)
            if nx < 0 or nx + 12 > n:
                break
            o = nx
    return out


def pick_endian(blob):
    """★ 用 CRC 通过率反推端序，不靠猜"""
    best = None
    for e, name in ((">", "大端(标准)"), ("<", "小端(非标准)")):
        ns = scan_nodes(blob, e)
        ok = sum(1 for x in ns if x[3])
        types = collections.Counter(t for _, t, _, _ in ns)
        sensible = sum(v for k, v in types.items() if k in NTYPE)
        print("  试 %-14s 节点 %-6d CRC通过 %-6d 类型合理的 %-6d" % (name, len(ns), ok, sensible))
        score = (ok, sensible, len(ns))
        if best is None or score > best[0]:
            best = (score, e, name, ns)
    return best[1], best[2], best[3]


def decomp(compr, data, dsize):
    try:
        if compr == 0:
            return data
        if compr == 1:
            return b"\x00" * dsize
        if compr == 6:
            return zlib.decompress(data)
        if compr == 8:
            import lzma
            return lzma.decompress(data)
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser(description="从裸镜像提取 JFFS2（自动判端序）")
    ap.add_argument("image")
    ap.add_argument("-o", "--out", default="jffs2_out")
    a = ap.parse_args()

    blob = pathlib.Path(a.image).read_bytes()
    print("镜像 %s（%d 字节）" % (a.image, len(blob)))
    print("判端序（★ 用 CRC 通过率决定，不猜）:")
    endian, ename, nodes = pick_endian(blob)
    good = [x for x in nodes if x[3]]
    print("→ 选定 %s，合法节点 %d 个（其中 CRC 通过 %d）" % (ename, len(nodes), len(good)))
    if not good:
        print("✗ 没有 CRC 通过的节点 —— 这份镜像可能确实不是 JFFS2，或端序还不是这两种之一")
        return 1

    dirents, inodes = [], []
    for off, ntype, totlen, ok in nodes:
        if not ok:
            continue
        if ntype == 0xE001:
            pino, ver, ino, mctime = struct.unpack(endian + "IIII", blob[off+12:off+28])
            nsize, dtype = struct.unpack("<BB", blob[off+28:off+30])
            dirents.append((ino, blob[off+40:off+40+nsize], dtype))
        elif ntype == 0xE002:
            # ★ 注意 uid/gid 是 u16（写成 u32 会让后面所有字段错 2 字节）
            (ino, ver, mode, uid, gid, isize, atime, mtime, ctime,
             offset, csize, dsize) = struct.unpack(endian + "IIIHHIIIIIII", blob[off+12:off+56])
            compr, ucc, flags = struct.unpack("<BBH", blob[off+56:off+60])
            inodes.append((ino, ver, offset, csize, dsize, compr, isize,
                           blob[off+68:off+68+csize]))

    by_ino = collections.defaultdict(list)
    for r in inodes:
        by_ino[r[0]].append(r)
    names = collections.defaultdict(list)
    for ino, name, dtype in dirents:
        names[ino].append(name)

    print("\ninode %d 个，DIRENT %d 个" % (len(by_ino), len(dirents)))
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n_written = 0
    for ino, recs in by_ino.items():
        recs.sort(key=lambda r: r[1])          # ★ 按【版本升序】，后写覆盖先写
        size = max(r[6] for r in recs)         # isize
        buf = bytearray(size)
        bad = False
        for (_i, _v, offset, csize, dsize, compr, _isize, data) in recs:
            d = decomp(compr, data, dsize)
            if d is None:
                bad = True
                break
            buf[offset:offset+len(d)] = d
        for name in names.get(ino, [b"ino%d" % ino]):
            safe = re.sub(rb"[^\w.\-+]", b"_", name).decode() or ("ino%d" % ino)
            (out / safe).write_bytes(bytes(buf))
            n_written += 1
            print("  %-28s %9d 字节  节点 %-4d%s"
                  % (safe, size, len(recs), "  ⚠含无法解压的块(lzo?)" if bad else ""))
    print("\n写出 %d 个文件 → %s" % (n_written, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
