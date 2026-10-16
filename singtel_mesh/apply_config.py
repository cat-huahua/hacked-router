#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拿到会话后，一次性把 mesh 配成你要的样子。

  读当前 17 段 -> 只替换 SSID / 密码 / 两个信道 -> 写回
  然后重命名四个节点

用法:
    python3 apply_config.py --dry-run     # 只读并显示将要写入的内容
    python3 apply_config.py --apply       # 真写
"""
import argparse, sys, time
sys.path.insert(0, "/home/ma-xiuyuan/singtel_mesh")
from sg import Mesh
from setch import read_cfg, build_payload

# ★ 你要的目标值
SSID24 = "MyHome"
SSID5  = "MyHome_5G"
WPA    = "WIFI_PASSWORD_HERE"
CH24   = "11"
CH5    = "153"          # 非 DFS，且避开 149

NODES = [
    ("AA:BB:CC:00:00:01", "NODE_NAME_1", "3.2  主控"),
    ("AA:BB:CC:00:00:02", "NODE_NAME_2", "3.20 节点2"),
    ("AA:BB:CC:00:00:03", "NODE_NAME_3", "3.21 节点3"),
    ("AA:BB:CC:00:00:04", "NODE_NAME_4", "3.22 节点4"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pw", default="FACTORY_PASSWORD_HERE", help="登录密码")
    a = ap.parse_args()

    m = Mesh("192.168.3.2", "admin", a.pw)
    print("登录中...")
    r = m.s.post(m.base + "/login.cgi", timeout=10, allow_redirects=False, data=None) if False else None
    m.login()                      # sg.Mesh.login() 用的是 self.pw
    print("  ✓ 会话已建立")

    cfg = read_cfg(m)
    print()
    print("当前无线设置：")
    print("  2.4G SSID = %r" % cfg.get("24gname0"))
    print("  5G   SSID = %r" % cfg.get("5gname0"))
    print("  2.4G 密码 = %r" % cfg.get("24gwpapsk0"))
    print("  5G   密码 = %r" % cfg.get("5gwpapsk0"))
    print("  信道      = %s / %s" % (cfg.get("channel_24ghz"), cfg.get("channel_5ghz")))

    # 用目标值覆盖
    cfg["24gname0"] = SSID24
    cfg["5gname0"] = SSID5
    cfg["24gwpapsk0"] = WPA
    cfg["5gwpapsk0"] = WPA

    payload, fields = build_payload(cfg, CH24, CH5)
    labels = ["2.4G SSID", "5G SSID", "2.4G bcast", "5G bcast", "2.4G sec", "5G sec",
              "2.4G psk", "5G psk", "wps", "★2.4G ch", "★5G ch", "24g bw", "24g coex",
              "ldpc", "5g bw", "5g coex", "5g vht"]
    print()
    print("将写入：")
    for lb, v in zip(labels, fields):
        print("  %-12s = %r" % (lb, v))

    if not a.apply:
        print("\n（只读模式，加 --apply 才真写）")
        return

    tok = m._token()
    r = m.s.post(m.base + "/cgi-bin/toplogy.cgi", timeout=25, allow_redirects=False,
                 data={"httoken": tok, "cmd": "syncwificonfig", "data": payload})
    print("\n写入返回: %r" % r.text.strip()[:80])
    if r.text.strip() != "ok_wifi":
        print("✗ 不是 ok_wifi，检查上面的字段")
        return

    print("等 mesh 同步（会短暂断线）...")
    time.sleep(30)
    for _ in range(10):
        try:
            c = read_cfg(m)
            print("  回读: SSID=%r 密码=%r 信道=%s/%s"
                  % (c.get("24gname0"), c.get("24gwpapsk0"),
                     c.get("channel_24ghz"), c.get("channel_5ghz")))
            break
        except Exception:
            print("  控制器还没回来，再等 10 秒"); time.sleep(10)

    print("\n重命名四个节点 ...")
    for lan, name, label in NODES:
        try:
            rr = m.rename_node(lan, name)
            print("  %-16s -> %-16s %s" % (label, name, rr.text.strip()))
        except Exception as e:
            print("  %-16s ✗ %s" % (label, str(e)[:50]))
        time.sleep(3)
    print("\n完成。")


if __name__ == "__main__":
    main()
