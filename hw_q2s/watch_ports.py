#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时盯华为主路由的三个 LAN 口 + mesh 四台是否上线。
端口状态一变就打印一行 —— 方便你换网线/换口的时候看到即时反应。

接口编号是面板丝印的反序：
    接口 LAN3 = 面板 1 = mesh
    接口 LAN2 = 面板 2 = NETGEAR
    接口 LAN1 = 面板 3 = WAN
"""
import sys
import time

sys.path.insert(0, "/home/ma-xiuyuan/hw_q2s")
import router as R  # noqa: E402

MESH_IPS = ["192.168.3.2", "192.168.3.20", "192.168.3.21", "192.168.3.22"]
LABEL = {"3": "面板1(mesh)", "2": "面板2(NETGEAR)", "1": "面板3(WAN)"}
PORTS = ("3", "2", "1")

rt = R.Router()
rt.login("admin", "WIFI_PASSWORD_HERE")
print("开始监视（Ctrl-C 停）—— 只在状态变化时输出")
print("  格式：面板口=通/断@速率    mesh在线几台\n")

prev = None
prev_mesh = None
while True:
    try:
        d = {e["PortName"]: e for e in rt.get("ntwk/ethnegotiation")["ethintflist"]}
        cur = tuple((p, bool(d.get(p, {}).get("Status")), d.get(p, {}).get("Speed"))
                    for p in PORTS)
        h = rt.get("system/HostInfo")
        meshup = sum(1 for x in h
                     if (x.get("IPAddress") in MESH_IPS) and str(x.get("Active")) == "True")
        if cur != prev or meshup != prev_mesh:
            line = "  ".join(f"{LABEL[p]}={'通' if st else '断'}/{sp or '-'}"
                             for p, st, sp in cur)
            print(f"[{time.strftime('%H:%M:%S')}] {line}   mesh在线 {meshup}/4", flush=True)
            prev, prev_mesh = cur, meshup
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] 读取出错: {str(e)[:70]}", flush=True)
    time.sleep(6)
