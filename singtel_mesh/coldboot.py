#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冷启动后：等设备回来 -> 读 wait_secs -> 若归零则只试一次 ROUTER_PASSWORD_HERE"""
import re, sys, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, "/home/ma-xiuyuan/singtel_mesh")
from sg import Mesh, arcmd5
BASE = "https://192.168.3.2"

def page():
    s = requests.Session(); s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155.0"})
    t = s.get(BASE + "/login.htm", timeout=6).text
    m = re.search(r'wait_secs\s*=\s*parseInt\("(-?\d+)"\)', t)
    return int(m.group(1)) if m else None

print("等冷启动完成...", flush=True)
w = None; end = time.time() + 600
while time.time() < end:
    try:
        w = page(); print("   wait_secs = %s" % w, flush=True)
        if w == 0: break
    except Exception as e:
        print("   还没起来 (%s)" % type(e).__name__, flush=True)
    time.sleep(12)

if w != 0:
    print("\n✗ 冷启动后 wait_secs 仍是 %s —— 那锁就确实在闪存里。" % w, flush=True)
    sys.exit(0)

print("\n★★★ 锁清了！立刻用 ROUTER_PASSWORD_HERE 试一次：", flush=True)
m = Mesh("192.168.3.2", "admin", "ROUTER_PASSWORD_HERE")
t = m._token()
r = m.s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False,
             data={"url": "", "name": arcmd5(arcmd5("admin") + t),
                   "pws": arcmd5(arcmd5("ROUTER_PASSWORD_HERE") + t), "httoken": t})
print("   admin/ROUTER_PASSWORD_HERE -> %s" % r.headers.get("Location", "?"), flush=True)
