#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kallsyms_extract —— 从【裸内核二进制】里解出 kallsyms 全符号表

内核把符号名**压缩**存储（token 化），所以 `strings` 只能捞到零星几个。
这个工具把它完整解出来 —— 一次能拿到几万个函数名（含厂商自己的）。

原理（三张表）：
    kallsyms_token_table   256 个 NUL 结尾的「片段」
    kallsyms_token_index   256 个 u16 偏移，指回 token_table
    kallsyms_names         每个符号 = [长度][长度个 token 索引]
    （名字首字符是**类型**：T=全局代码 t=局部代码 r=只读数据 b=BSS d=数据 …）

两个坑：
  ① token_table 的判据必须严格 —— 只靠"256 个 u16 递增"会把**整片零**误判成表
     （本工具要求 ≥200 个非空 token 且总长 ≥400 字节）
  ② 找到表之后还要找 names 段的**对齐起点**（每个符号的长度字节在哪）。
     做法：在表之前扫，找第一个能连续解出 ≥100 个合法符号名的位置。
     比"猜偏移"可靠得多。

用法:
    python3 kallsyms_extract.py <vmlinux>  [-o 输出文件]

实测（2026-10-17）：
    Singtel Mesh Router  vmlinux (Linux 4.1.38)  → 39,965 个符号名
    NETGEAR DSL-AC87VG   vmlinux (Linux 3.4.11)  → 17,483 个符号名
"""
import argparse
import pathlib
import re
import struct
import sys

NAME_CHARS = set(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.$")
# kallsyms 的符号类型字符（nm(1) 风格）
TYPE_CHARS = set(b"TtRrBbDdAaWwVvNnGgSsCcUuIi")


def read_token_table(d, i, check_index=True):
    """从 i 读 256 个 token，并校验紧跟的 token_index"""
    toks, p = [], i
    for _ in range(256):
        e = d.find(b"\x00", p, p + 64)
        if e < 0:
            return None
        toks.append(d[p:e])
        p = e + 1
    # ★ 严格判据：拒绝「全空/几乎全空」的假表
    nonempty = sum(1 for t in toks if t)
    if nonempty < 200 or sum(len(t) for t in toks) < 400:
        return None
    if not check_index:
        return toks, p
    if p + 512 > len(d):
        return None
    idx = struct.unpack("<256H", d[p:p + 512])
    offs, q = [], i
    for t in toks:
        offs.append(q - i)
        q += len(t) + 1
    if sum(1 for a, b in zip(offs, idx) if abs(a - b) <= 4) < 250:
        return None
    return toks, p


def find_token_table(d):
    """找 token_table。★ 先做廉价预筛，否则要逐 4 字节扫几百万次（实测慢到不可用）

    注意 token_table 是【NUL 分隔的短串】，所以整体可打印率并不高 ——
    不能用"可打印率高"来筛（会把正确的表筛掉）。改判据：
    第一个 token 必须是「非空且 ≤7 字符」的短串。"""
    n = len(d)
    for i in range(0, n - 1024, 4):
        nl = d.find(b"\x00", i, i + 8)
        if nl <= i:                      # 第一个 token 为空 / 超过 7 字符
            continue
        r = read_token_table(d, i)
        if r:
            return i, r[0], r[1]
    return None


def decode_run(d, toks, start, limit=300000):
    names, i = [], start
    n_d = len(d)
    while len(names) < limit and i < n_d - 2:
        n = d[i]
        i += 1
        if n & 0x80:                      # 两字节长度
            n = (n & 0x7F) | (d[i] << 7)
            i += 1
        if n == 0 or n > 200:
            break
        nm = b""
        for _ in range(n):
            if i >= n_d:
                return names
            nm += toks[d[i]]
            i += 1
        if not nm or len(nm) > 80:
            break
        if nm[0] not in TYPE_CHARS or any(c not in NAME_CHARS for c in nm[1:]):
            break
        names.append(nm)
    return names


def find_alignment(d, toks, tt_start):
    """在 token_table 之前找 names 段的对齐起点

    ★ 判据的演进（都是实测踩出来的）：
      · "能连续解出 100 个合法字符的名字" —— 不够，错位解码同样能解出一大串
      · 加"多样性 ≥150/200" —— 仍不够，见过 `init4_A` 重复 69 次却仍够唯一值的
      · 最终答案：**取解出名字最多的那个起点**。正确的对齐能一路解到几万个，
        错位的解几百个就因长度字节错位而断掉 —— 差异是数量级。

    两趟做（否则太慢）：先每题只解 60 个快速筛出候选，再对候选长解比数量。
    """
    cands = []
    for s in range(0, tt_start):
        if not (3 <= d[s] <= 40):
            continue
        if len(decode_run(d, toks, s, 60)) >= 55:
            cands.append(s)          # ★ 不要截断：真正的对齐可能在很后面
    if not cands:
        return None
    best_s, best_n = None, 0
    for s in cands:
        n = len(decode_run(d, toks, s, 4000))
        if n > best_n:
            best_n, best_s = n, s
        if best_n >= 4000:
            break
    return best_s


def main():
    ap = argparse.ArgumentParser(description="从裸内核解出 kallsyms 符号表")
    ap.add_argument("vmlinux")
    ap.add_argument("-o", "--out", help="输出文件（默认 <输入>.ksyms.txt）")
    a = ap.parse_args()

    p = pathlib.Path(a.vmlinux)
    d = p.read_bytes()
    print("文件: %s (%d 字节)" % (p, len(d)))

    r = find_token_table(d)
    if not r:
        print("✗ 找不到 kallsyms token_table —— 可能不是内核，或符号表被去掉了")
        return 1
    tt_start, toks, tt_end = r
    print("★ token_table @0x%X（index @0x%X），示例 token: %s"
          % (tt_start, tt_end, [t.decode("latin1") for t in toks[:10]]))

    s = find_alignment(d, toks, tt_start)
    if s is None:
        print("✗ 找不到 names 段的对齐起点")
        return 1
    print("★ names 段对齐起点 @0x%X" % s)

    names = decode_run(d, toks, s)
    print("★ 解出 %d 个符号名" % len(names))
    if names:
        print("   前 12: %s" % [n.decode("latin1") for n in names[:12]])

    out = pathlib.Path(a.out or (str(p) + ".ksyms.txt"))
    out.write_text("\n".join(n.decode("latin1") for n in names))
    print("→ %s" % out)

    # 顺手按厂商/功能前缀统计
    bare = [n[1:].decode("latin1") for n in names]
    print("\n按前缀统计（前 15）:")
    prefixes = {}
    for n in bare:
        k = re.match(r"[A-Za-z]+_?", n)
        if k:
            prefixes[k.group(0)] = prefixes.get(k.group(0), 0) + 1
    for k, v in sorted(prefixes.items(), key=lambda x: -x[1])[:15]:
        print("   %-16s %5d" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
