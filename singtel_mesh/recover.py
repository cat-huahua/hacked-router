#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recover Singtel —— 一键把 Singtel mesh 的设置恢复到你要的状态。

断电重插 / mesh 自己抽风之后跑一次就行。

恢复两样东西：
  1. 信道：2.4G -> 11，5G -> 40
  2. 四台节点名：NODE_NAME_1 / NODE_NAME_2 / NODE_NAME_3 / NODE_NAME_4（顺带同步到华为 3.1）

用法：
    python3 recover.py            # 都恢复
    python3 recover.py --ch       # 只恢复信道
    python3 recover.py --name     # 只恢复名字
"""
import argparse
import re
import sys
import time

sys.path.insert(0, "/home/ma-xiuyuan/singtel_mesh")
from sg import Mesh                       # noqa: E402
from setch import read_cfg, build_payload, CH24, CH5   # noqa: E402

# 节点：网卡 MAC -> 想要的内部名（内部 MAC 由 Mesh.inner_mac 自动 +1）
NODES = [
    ("AA:BB:CC:00:00:01", "NODE_NAME_1", "3.2  主节点"),
    ("AA:BB:CC:00:00:02", "NODE_NAME_2", "3.20 节点2"),
    ("AA:BB:CC:00:00:03", "NODE_NAME_3", "3.21 节点3"),
    ("AA:BB:CC:00:00:04", "NODE_NAME_4", "3.22 节点4"),
]
HUAWEI = "192.168.3.1"
HW_USER, HW_PW = "admin", "WIFI_PASSWORD_HERE"


def do_channels():
    print("══════ ① 恢复无线信道 ══════")
    m = Mesh(); m.login()
    cfg = read_cfg(m)
    print(f"  当前: 2.4G={cfg.get('channel_24ghz')}  5G={cfg.get('channel_5ghz')}")
    print(f"  目标: 2.4G={CH24}  5G={CH5}")

    # 原样回填其他字段（含 SSID / 密码），只改信道两段
    payload, _ = build_payload(cfg, CH24, CH5)
    tok = m._token()
    r = m.s.post(m.base + "/cgi-bin/toplogy.cgi",
                 data={"httoken": tok, "cmd": "syncwificonfig", "data": payload},
                 timeout=20, allow_redirects=False)
    print(f"  写入: {r.text.strip()!r}")
    if r.text.strip() != "ok_wifi":
        print("  ✗ 没拿到 ok_wifi，信道可能没写进去")
        return False

    print("  等 mesh 同步（会短暂断线）...")
    time.sleep(25)
    for _ in range(8):
        try:
            c = read_cfg(m)
            a, b = c.get("channel_24ghz"), c.get("channel_5ghz")
            ok = (a == CH24 and b == CH5)
            print(f"  回读: 2.4G={a}  5G={b}   SSID={c.get('24gname0')}   密码={c.get('24gwpapsk0')}")
            print("  ✅ 信道已恢复" if ok else "  ⚠ 信道还没对上")
            return ok
        except Exception:
            print("  控制器还没回来，再等 10 秒")
            time.sleep(10)
    return False


def do_names():
    print("\n══════ ② 恢复节点名 ══════")
    m = Mesh(); m.login()
    print(f"  主节点当前名: {m.friendly_name()}")
    for lan, name, label in NODES:
        try:
            r = m.rename_node(lan, name)
            print(f"  {label:16} -> \"{name}\"   {r.text.strip()}")
        except Exception as e:
            print(f"  {label:16} ✗ {str(e)[:50]}")
        time.sleep(3)
    time.sleep(5)
    try:
        got = m.friendly_name()
        print(f"  主节点回读: {got}   {'✅' if got == NODES[0][1] else '⚠'}")
    except Exception as e:
        print(f"  回读失败（控制器在重启）：{str(e)[:50]}")

    # 顺手同步到华为 3.1，让两边的设备列表一致
    print("\n  同步到华为 3.1 ...")
    try:
        sys.path.insert(0, "/home/ma-xiuyuan/hw_q2s")
        import router as R
        rt = R.Router(); rt.login(HW_USER, HW_PW)
        h = rt.get("system/HostInfo")
        for lan, name, label in NODES:
            x = next((i for i in h if (i.get("MACAddress") or "").upper() == lan), None)
            if not x:
                print(f"    {label:16} 不在主机表，跳过"); continue
            old = x.get("ActualName") or ""
            if old == name:
                print(f"    {label:16} 已经是 \"{name}\"，跳过"); continue
            rt.post("system/changedevicename",
                    {"action": "update", "data": [{"ActualName": name, "ID": x["ID"]}]})
            print(f"    {label:16} \"{old[:26]}\" -> \"{name}\"")
            time.sleep(0.4)
    except Exception as e:
        print(f"    华为侧失败（不影响 Singtel）：{str(e)[:60]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ch", action="store_true", help="只恢复信道")
    ap.add_argument("--name", action="store_true", help="只恢复名字")
    a = ap.parse_args()
    both = not (a.ch or a.name)

    print("╔══════════════════════════════════════════╗")
    print("║  Recover Singtel — 恢复 mesh 设置        ║")
    print("╚══════════════════════════════════════════╝\n")
    ok = True
    if both or a.ch:
        ok &= bool(do_channels())
    if both or a.name:
        do_names()
    print("\n完成。" + ("" if ok else "  ⚠ 有步骤没成功，看上面日志。"))


if __name__ == "__main__":
    main()
