#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全登录：先看 wait_secs，只有为 0 才发一次登录请求。"""
import re, sys, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, "/home/ma-xiuyuan/singtel_mesh")
from sg import Mesh, arcmd5

BASE = "https://192.168.3.2"

def wait_secs():
    s = requests.Session(); s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155.0"})
    t = s.get(BASE + "/login.htm", timeout=8).text
    m = re.search(r'wait_secs\s*=\s*parseInt\("(-?\d+)"\)', t)
    return int(m.group(1)) if m else None

def gate():
    s = requests.Session(); s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155.0"})
    r = s.get(BASE + "/index.htm", timeout=8, allow_redirects=False)
    return r.headers.get("Location", "")

def one(pwd):
    m = Mesh("192.168.3.2", "admin", pwd)
    t = m._token()
    r = m.s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False,
                 data={"url": "", "name": arcmd5(arcmd5("admin") + t),
                       "pws": arcmd5(arcmd5(pwd) + t), "httoken": t})
    return r.headers.get("Location", "?"), m

pwd = sys.argv[1] if len(sys.argv) > 1 else "FACTORY_PASSWORD_HERE"
print("倒计时: %s   /index.htm 跳转: %s" % (wait_secs(), gate()), flush=True)
w = wait_secs()
if w not in (0,):
    print("→ 倒计时未清零（%s），不试，避免再次锁定" % w); sys.exit(0)
loc, m = one(pwd)
print("admin/%s -> %s" % (pwd, loc), flush=True)
if loc == "/index.htm":
    print("★ 登录成功")
    for p in ["/index.htm", "/ssid.htm", "/status_lan_device.htm"]:
        rr = m.s.get(BASE + p, timeout=8, allow_redirects=False)
        print("   GET %-24s %s %s" % (p, rr.status_code, rr.headers.get("Location", "")))
