#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cfgkeys —— 暴力枚举 Arcadyan `libarccfg` 里**所有可能的配置键**

为什么需要：
  `.glbcfg` 里只有 2361 个键，但 `libarccfg.so` 的字段表定义了 2000+ 个模板，
  每个模板加上索引上限（x/y）后能展开出 **3 万多个可能键**。
  很多“后台开关”不在 `.glbcfg` 里，但可以用 `mng_cli get <键>` 直接读。

原理：
  字段表每项 32 字节：
      [名字指针][格式串指针][idx1 上限][0][idx2 上限][0][0][0]
  格式串里的 `%d` / `%02d` 就是索引；idx1/idx2 上限决定能展开多少。

用法:
    python3 cfgkeys.py <rootfs目录>                 # 打印所有键
    python3 cfgkeys.py <rootfs目录> --missing       # 只打印 .glbcfg 里没有的
    python3 cfgkeys.py <rootfs目录> -o keys.txt     # 导出

实测（v5.02.00）：2155 个模板 → 38,193 个键；.glbcfg 只用了 2,361 个。
"""
import argparse
import pathlib
import re
import struct
import subprocess
import sys

MODULES = [
    "ARC_TEST", "ARC_WAN", "ARC_LAN", "ARC_WLAN", "ARC_VO", "ARC_UI",
    "ARC_SYS", "ARC_TR64", "ARC_TR69", "ARC_BOOTSTRAP", "ARC_FIREWALL",
    "ARC_QOS", "ARC_NAT", "ARC_USB", "ARC_UPNP", "ARC_PROJ", "ARC_ROUTE",
    "ARC_IP6", "ARC_DDNS", "ARC_IGMP", "ARC_VPN", "ARC_OMCI", "ARC_OWL",
]


def readelf_sections(path):
    out = subprocess.run(["readelf", "-SW", str(path)], capture_output=True, text=True).stdout
    secs = []
    for line in out.splitlines():
        m = re.match(r"\s*\[\s*\d+\]\s+(\S+)\s+\S+\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", line)
        if m:
            secs.append((m.group(1), int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16)))
    return secs


def readelf_objects(path):
    out = subprocess.run(["readelf", "-sW", str(path)], capture_output=True, text=True).stdout
    syms = {}
    for line in out.splitlines():
        m = re.match(r"\s*\d+:\s+([0-9a-f]+)\s+(\d+)\s+OBJECT\s+GLOBAL\s+DEFAULT\s+\d+\s+(\S+)", line)
        if m:
            syms[m.group(3)] = (int(m.group(1), 16), int(m.group(2)))
    return syms


class Keys:
    def __init__(self, so_path):
        self.d = pathlib.Path(so_path).read_bytes()
        self.secs = readelf_sections(so_path)
        self.syms = readelf_objects(so_path)

    def off(self, vaddr):
        for _n, va, fo, size in self.secs:
            if va <= vaddr < va + size:
                return fo + (vaddr - va)
        return None

    def cstr(self, vaddr):
        o = self.off(vaddr)
        if o is None:
            return None
        e = self.d.find(b"\0", o, o + 200)
        if e < 0:
            return None
        try:
            s = self.d[o:e].decode("ascii")
        except UnicodeDecodeError:
            return None
        return s if s and all(32 <= ord(c) < 127 for c in s) else None

    def generate(self):
        keys = set()
        templates = 0
        for mod in MODULES:
            sym = "arc_%s_cfg_item_table" % mod.lower().replace("arc_", "")
            if sym not in self.syms:
                continue
            va, size = self.syms[sym]
            for i in range(size // 32):
                o = self.off(va + i * 32)
                if o is None:
                    continue
                w = struct.unpack("<8I", self.d[o:o + 32])
                fmt = self.cstr(w[1])
                if not fmt:
                    continue
                templates += 1
                n1, n2 = w[2], w[4]
                for a in (range(n1) if n1 else [None]):
                    for b in (range(n2) if n2 else [None]):
                        try:
                            if a is not None and b is not None:
                                k = fmt % (a, b)
                            elif a is not None:
                                k = fmt % a
                            else:
                                k = fmt
                        except (TypeError, ValueError):
                            continue
                        keys.add(k)
        return templates, keys


def glbcfg_keys(root):
    for p in pathlib.Path(root).rglob(".glbcfg"):
        out = set()
        for line in p.read_text("latin1", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                out.add(line.split("=", 1)[0].strip())
        return out
    return set()


def main():
    ap = argparse.ArgumentParser(description="暴力枚举 libarccfg 的全部可能配置键")
    ap.add_argument("rootfs")
    ap.add_argument("--missing", action="store_true", help="只打印 .glbcfg 里没有的（未使用的索引）")
    ap.add_argument("--unmapped", action="store_true", help="只打印 .glbcfg 有、但字段表没生成的键")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    root = pathlib.Path(a.rootfs)
    so = None
    for p in (root / "usr/lib/libarccfg.so.0.1", root / "usr/lib/libarccfg.so"):
        if p.exists():
            so = p
            break
    if not so:
        print("✗ 找不到 libarccfg.so")
        return 1

    templates, keys = Keys(so).generate()
    cfg = glbcfg_keys(root)
    print("模板 %d 个 → 可能键 %d 个；.glbcfg 实际 %d 个" % (templates, len(keys), len(cfg)))

    if cfg:
        miss = sorted(keys - cfg)
        print("定义但 .glbcfg 没有：%d 个" % len(miss))
        print("（这些就是可以 `mng_cli get` 试探的隐藏字段）")

    if a.unmapped and cfg:
        out_keys = sorted(cfg - keys)
        print("`.glbcfg` 有、字段表没生成：%d 个" % len(out_keys))
        print("（多来自 %%s 模板 / VAR_* / OMCI 等特殊表，值得单独看）")
    elif a.missing and cfg:
        out_keys = sorted(keys - cfg)
    else:
        out_keys = sorted(keys)
    if a.out:
        pathlib.Path(a.out).write_text("\n".join(out_keys) + "\n")
        print("→ %s（%d 个）" % (a.out, len(out_keys)))
    else:
        for k in out_keys:
            print(k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
