#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""断电重启后：等设备起来 -> 确认倒计时归零 -> 只用 ROUTER_PASSWORD_HERE 试一次"""
import re, sys, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, "/home/ma-xiuyuan/singtel_mesh")
from sg import Mesh, arcmd5

BASE = "https://192.168.3.2"
NEW, OLD = "ROUTER_PASSWORD_HERE", "FACTORY_PASSWORD_HERE"

def page():
    s = requests.Session(); s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155.0"})
    t = s.get(BASE + "/login.htm", timeout=6).text
    m = re.search(r'wait_secs\s*=\s*parseInt\("(-?\d+)"\)', t)
    return int(m.group(1)) if m else None

print("等设备起来...", flush=True)
deadline = time.time() + 420
w = None
while time.time() < deadline:
    try:
        w = page()
        print("   wait_secs = %s" % w, flush=True)
        if w == 0:
            break
    except Exception as e:
        print("   还没起来 (%s)" % type(e).__name__, flush=True)
    time.sleep(10)

if w != 0:
    print("✗ 没等到倒计时归零，w=%s。不试登录，避免再次锁死。" % w, flush=True)
    sys.exit(1)

print("\n倒计时 0，用 ROUTER_PASSWORD_HERE 试一次：", flush=True)
m = Mesh("192.168.3.2", "admin", NEW)
t = m._token()
r = m.s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False,
             data={"url": "", "name": arcmd5(arcmd5("admin") + t),
                   "pws": arcmd5(arcmd5(NEW) + t), "httoken": t})
loc = r.headers.get("Location", "?")
print("   admin/%s -> %s" % (NEW, loc), flush=True)

if loc == "/index.htm":
    print("\n★★★ 登录成功 —— 密码就是 ROUTER_PASSWORD_HERE ★★★", flush=True)
    open("/tmp/mesh_ok", "w").write("1")
    for p in ["/ssid.htm", "/status_lan_device.htm", "/index.htm"]:
        rr = m.s.get(BASE + p, timeout=8, allow_redirects=False)
        print("   GET %-24s %s %s" % (p, rr.status_code, rr.headers.get("Location", "")), flush=True)
    import pickle
    pickle.dump(m.s.cookies, open("/tmp/mesh_cookies.pkl", "wb"))
else:
    print("\n✗ 新密码被拒。待查：是否落成了 encode 后的字面串。", flush=True)
