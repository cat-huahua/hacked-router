#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webmap —— 把 Singtel/Arcadyan web 界面里的字段，翻译成真正的 `ARC_*` 配置键

为什么需要它：
  web 界面的 JS 里不是直接写 `ARC_SYS_Password`，而是写一个**数字 ID**：

      <%ABS_MAP("gateway_id","393231")%>
      addCfg("def_lanip",0,"<% ABS_DFT("131076"+0) %>");

  这些数字其实是有结构的：

      id = (模块号 << 16) | 字段序号
      0x6000F → 模块 6（ARC_SYS）第 15 项 → ARC_SYS_SerialNum
      0x20003 → 模块 2（ARC_LAN）第 3 项  → ARC_LAN_x_MACaddr

  映射表在 `usr/lib/libarccfg.so` 的 `mod_table` + `arc_*_cfg_item_table` 里，
  每项 32 字节：{名字指针, 格式串指针, …}。本工具直接从 .so 里读出来。

三种宏：
  ABS_MAP("js_var","<id>")      单值字段
  ABS_ARR("js_var","<id>")      数组/多实例字段
  ABS_DFT("<id>")               出厂默认值
  addCfg("js_var","ARC_KEY",v)  直接给键名（不经过数字 ID）

用法:
    python3 webmap.py <rootfs目录> [-o webmap.tsv]
    python3 webmap.py <rootfs目录> --keys     # 只列 www 里出现的 ARC 键

实测（v5.02.00 build09b）：解析出三位数的字段映射，全部能落到具体 ARC 键。
"""
import argparse
import pathlib
import re
import struct
import subprocess
import sys

# mod_table 的顺序（libarccfg.so 里 23 项）
MODULES = [
    "ARC_TEST", "ARC_WAN", "ARC_LAN", "ARC_WLAN", "ARC_VO", "ARC_UI",
    "ARC_SYS", "ARC_TR64", "ARC_TR69", "ARC_BOOTSTRAP", "ARC_FIREWALL",
    "ARC_QOS", "ARC_NAT", "ARC_USB", "ARC_UPNP", "ARC_PROJ", "ARC_ROUTE",
    "ARC_IP6", "ARC_DDNS", "ARC_IGMP", "ARC_VPN", "ARC_OMCI", "ARC_OWL",
]


class CfgTable:
    """从 libarccfg.so 里读 mod_table / item_table"""

    def __init__(self, so_path):
        self.d = pathlib.Path(so_path).read_bytes()
        self.sections = self._sections(so_path)
        self.syms = self._syms(so_path)

    def _sections(self, so_path):
        out = subprocess.run(["readelf", "-SW", str(so_path)],
                             capture_output=True, text=True).stdout
        secs = []
        for line in out.splitlines():
            m = re.match(r"\s*\[\s*\d+\]\s+(\S+)\s+\S+\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", line)
            if m:
                secs.append((m.group(1), int(m.group(2), 16),
                             int(m.group(3), 16), int(m.group(4), 16)))
        return secs

    def _syms(self, so_path):
        out = subprocess.run(["readelf", "-sW", str(so_path)],
                             capture_output=True, text=True).stdout
        syms = {}
        for line in out.splitlines():
            m = re.match(r"\s*\d+:\s+([0-9a-f]+)\s+(\d+)\s+OBJECT\s+GLOBAL\s+DEFAULT\s+\d+\s+(\S+)", line)
            if m:
                syms[m.group(3)] = (int(m.group(1), 16), int(m.group(2)))
        return syms

    def _off(self, vaddr):
        for _name, va, fo, size in self.sections:
            if va and va <= vaddr < va + size:
                return fo + (vaddr - va)
        return None

    def _cstr(self, vaddr):
        o = self._off(vaddr)
        if o is None or not (0 <= o < len(self.d)):
            return None
        e = self.d.find(b"\0", o, o + 128)
        if e < 0:
            return None
        try:
            s = self.d[o:e].decode("ascii")
        except UnicodeDecodeError:
            return None
        return s if s and all(32 <= ord(c) < 127 for c in s) else None

    def lookup(self, cid):
        """id → (ARC 名字模板, 格式串)"""
        mod = (cid >> 16) & 0xFFFF
        idx = cid & 0xFFFF
        if mod >= len(MODULES):
            return None, None
        sym = "arc_%s_cfg_item_table" % MODULES[mod].lower().replace("arc_", "")
        if sym not in self.syms:
            return None, None
        va, size = self.syms[sym]
        if idx * 32 + 8 > size:
            return None, None
        p = va + idx * 32
        o = self._off(p)
        if o is None:
            return None, None
        name = self._cstr(struct.unpack("<I", self.d[o:o + 4])[0])
        fmt = self._cstr(struct.unpack("<I", self.d[o + 4:o + 8])[0])
        return name, fmt


def parse_id(s):
    """'393231' / '"393231"+0' / '131075' → int"""
    m = re.search(r"\d+", s or "")
    return int(m.group(0)) if m else None


ABS_MAP = re.compile(r'ABS_MAP\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')
ABS_ARR = re.compile(r'ABS_ARR\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')
ABS_DFT = re.compile(r'ABS_DFT\(\s*"([^"]+)"(?:\s*\+\s*\d+)?\s*\)')
ADDC_STR = re.compile(r'addCfg\(\s*"([^"]+)"\s*,\s*"([^"]+)"')
NVGET = re.compile(r'nvram_get\(\s*\\?"(ARC_[A-Z0-9_]+)\\?"')
ARCKEY = re.compile(r'ARC_[A-Z0-9_]+')


def scan(root):
    www = pathlib.Path(root) / "www"
    if not www.is_dir():
        print("✗ 找不到 www/（rootfs 路径不对？）")
        return None
    so = None
    for p in (pathlib.Path(root) / "usr/lib/libarccfg.so.0.1",
              pathlib.Path(root) / "usr/lib/libarccfg.so"):
        if p.exists():
            so = p
            break
    table = CfgTable(so) if so else None
    if not table:
        print("⚠ 找不到 libarccfg.so，数字 ID 只能显示模块/序号")

    rows = []
    for fp in sorted(www.rglob("*")):
        if fp.suffix.lower() not in (".js", ".htm", ".html"):
            continue
        txt = fp.read_text("latin1", errors="replace")
        rel = str(fp.relative_to(root))

        for m in ABS_MAP.finditer(txt):
            rows.append((rel, "ABS_MAP", m.group(1), m.group(2), *lookup(table, m.group(2))))
        for m in ABS_ARR.finditer(txt):
            rows.append((rel, "ABS_ARR", m.group(1), m.group(2), *lookup(table, m.group(2))))
        for m in ABS_DFT.finditer(txt):
            rows.append((rel, "ABS_DFT", "", m.group(1), *lookup(table, m.group(1))))

        # addCfg("var","ARC_KEY",value)
        for m in ADDC_STR.finditer(txt):
            key = m.group(2)
            if key.startswith("ARC_"):
                rows.append((rel, "addCfg", m.group(1), "", "", key, key))

        # 服务端宏里的 ARC 键
        for m in NVGET.finditer(txt):
            rows.append((rel, "nvram_get", "", "", "", m.group(1), m.group(1)))
    return table, rows


def lookup(table, s):
    cid = parse_id(s)
    if cid is None:
        return "", "", ""
    if not table:
        return "0x%X" % cid, "", ""
    name, fmt = table.lookup(cid)
    return ("0x%X" % cid, name or "", fmt or "")


def main():
    ap = argparse.ArgumentParser(description="Singtel web 字段 → ARC 配置键 映射")
    ap.add_argument("rootfs")
    ap.add_argument("-o", "--out")
    ap.add_argument("--keys", action="store_true", help="只列 www 里出现的 ARC 键")
    a = ap.parse_args()

    r = scan(a.rootfs)
    if not r:
        return 1
    table, rows = r

    if a.keys:
        keys = sorted({x[5] for x in rows if x[5]})
        for k in keys:
            print(k)
        print("\n共 %d 个键" % len(keys))
        return 0

    seen = set()
    out = []
    for rel, kind, var, raw, cid, name, fmt in rows:
        sig = (rel, kind, var, raw, cid, name, fmt)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(sig)

    print("解析出 %d 条映射（去重后）\n" % len(out))
    print("%-24s %-10s %-22s %-8s %-34s %s" %
          ("文件", "宏", "JS 变量", "数字ID", "ARC 键（模板）", "格式串"))
    for rel, kind, var, raw, cid, name, fmt in out:
        cid_s = cid if cid else (raw or "")
        print("%-24s %-10s %-22s %-8s %-34s %s"
              % (rel.replace("www/", ""), kind, var, cid_s, name or "?", fmt or ""))

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("file\tmacro\tjs_var\tid\tarc_name\tarc_format\n")
            for rel, kind, var, raw, cid, name, fmt in out:
                f.write("%s\t%s\t%s\t%s\t%s\t%s\n" %
                        (rel, kind, var, cid or raw, name, fmt))
        print("\n→ %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
