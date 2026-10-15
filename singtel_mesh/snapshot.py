#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 Singtel mesh 的全部设置拍一份快照，存成 JSON，方便和"已知良好"状态对比。

用法：
    python3 snapshot.py                  # 拍快照并打印
    python3 snapshot.py good.json        # 拍快照并保存到 good.json
    python3 snapshot.py now.json --diff good.json     # 和 good.json 比差异
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, "/home/ma-xiuyuan/singtel_mesh")
from sg import Mesh  # noqa: E402

# 所有已知 CGI（从 13 个页面的 CGIs=[...] 里收集的）
CGIS = ["status", "wifi", "wireless_wps", "toplogy_info", "lan", "upnp_main",
        "internet_cfg", "st", "sys_p", "led", "advance", "security_log"]

# 顶层 var（非 addCfg 的）
TOPVARS = ["lan_mac_addr_list", "wlan_mac_addr_list", "hardware_model",
           "hardware_version", "hardware_serial_no", "runtime_code_version",
           "system_uptime", "boot_code_version"]


def snap(m):
    out = {}
    for c in CGIS:
        try:
            t = m.cgi(c).text
        except Exception as e:
            out["_error_" + c] = str(e)[:80]
            continue
        for n, v in re.findall(r'addCfg\("([^"]+)",\s*"[0-9]+",\s*"([^"]*)"', t):
            out[n] = v
        for n in TOPVARS:
            mm = re.search(re.escape(n) + r'\s*=\s*("?[^;\n]{0,80})', t)
            if mm:
                out[n] = mm.group(1).strip().strip('"')
    try:
        out["_friendly_name"] = m.friendly_name()
    except Exception:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", help="保存到哪个 json")
    ap.add_argument("--diff", help="和这个 json 比差异")
    a = ap.parse_args()

    m = Mesh()
    m.login()
    s = snap(m)

    if a.diff and os.path.exists(a.diff):
        old = json.load(open(a.diff))
        print(f"═══ 与 {a.diff} 的差异 ═══")
        keys = sorted(set(old) | set(s))
        n = 0
        for k in keys:
            o, c = old.get(k, "(缺失)"), s.get(k, "(缺失)")
            if o != c:
                print(f"  ✗ {k:28} {o!r}  ->  {c!r}")
                n += 1
        print(f"\n  共 {n} 处变化" if n else "\n  ✅ 完全一致，没有任何设置被改")
    else:
        for k in sorted(s):
            print(f"  {k:28} = {s[k]}")

    if a.out:
        json.dump(s, open(a.out, "w"), ensure_ascii=False, indent=2, sort_keys=True)
        print(f"\n已保存 -> {a.out}")


if __name__ == "__main__":
    main()
