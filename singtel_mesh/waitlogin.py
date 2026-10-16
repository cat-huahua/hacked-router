#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等登录锁定倒计时归零，然后只用新密码登一次。绝不在倒计时中重试。"""
import os
import re, sys, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, os.path.expanduser("~/singtel_mesh"))
from sg import Mesh, arcmd5

HOST = "192.168.3.2"; BASE = "https://%s" % HOST
NEW = "ROUTER_PASSWORD_HERE"

def wait_secs():
    s = requests.Session(); s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155.0"})
    t = s.get(BASE + "/login.htm", timeout=8).text
    m = re.search(r'wait_secs\s*=\s*parseInt\("(-?\d+)"\)', t)
    return int(m.group(1)) if m else None

print("等锁定倒计时归零（期间不碰登录）...", flush=True)
deadline = time.time() + 600
while time.time() < deadline:
    w = wait_secs()
    print("   wait_secs = %s" % w, flush=True)
    if w == 0:
        break
    if w == -1:
        print("   ✗ 被永久锁定（wait_secs=-1）", flush=True); sys.exit(1)
    time.sleep(10)

print("\n倒计时已清零，用新密码登一次：", flush=True)
m = Mesh(HOST, "admin", NEW)
t = m._token()
r = m.s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False,
             data={"url": "", "name": arcmd5(arcmd5("admin") + t),
                   "pws": arcmd5(arcmd5(NEW) + t), "httoken": t})
loc = r.headers.get("Location", "?")
print("   admin/%s -> %s" % (NEW, loc), flush=True)
if loc == "/index.htm":
    print("   ★★★ 登录成功！密码已经改成 ROUTER_PASSWORD_HERE 了", flush=True)
    for page in ["/index.htm", "/ssid.htm", "/change_pwd.htm"]:
        rr = m.s.get(BASE + page, timeout=8, allow_redirects=False)
        print("      GET %-16s -> %s %s" % (page, rr.status_code, rr.headers.get("Location", "")), flush=True)
