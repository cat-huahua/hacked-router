#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等倒计时归零 -> 只试一次（可指定密码）。查倒计时用 GET，不算登录尝试。"""
import re, sys, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, "/home/ma-xiuyuan/singtel_mesh")
from sg import Mesh, arcmd5

BASE = "https://192.168.3.2"
PWDS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["FACTORY_PASSWORD_HERE"]

def probe():
    s = requests.Session(); s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155.0"})
    t = s.get(BASE + "/login.htm", timeout=8).text
    m = re.search(r'wait_secs\s*=\s*parseInt\("(-?\d+)"\)', t)
    w = int(m.group(1)) if m else None
    g = s.get(BASE + "/index.htm", timeout=8, allow_redirects=False).headers.get("Location", "-")
    return w, g

print("等倒计时归零...", flush=True)
end = time.time() + 900
while time.time() < end:
    w, g = probe()
    print("   wait_secs=%-5s /index.htm->%s" % (w, g), flush=True)
    if w == 0:
        break
    if w == -1:
        print("   ✗ 永久锁定"); sys.exit(1)
    time.sleep(15)

print("\n清零了，逐个试一次：", flush=True)
for pwd in PWDS:
    m = Mesh("192.168.3.2", "admin", pwd)
    t = m._token()
    r = m.s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False,
                 data={"url": "", "name": arcmd5(arcmd5("admin") + t),
                       "pws": arcmd5(arcmd5(pwd) + t), "httoken": t})
    loc = r.headers.get("Location", "?")
    print("   admin/%-12s -> %s" % (pwd, loc), flush=True)
    if loc == "/index.htm":
        print("   ★ 登录成功", flush=True)
        break
    w2, _ = probe()
    if w2 and w2 > 0:
        print("   （又被锁 %ss，停止尝试）" % w2, flush=True)
        break
