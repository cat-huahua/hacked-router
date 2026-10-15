#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探测：用 FACTORY_PASSWORD_HERE 登录后，看这个会话到底有多少权限。绝不写任何东西。"""
import re, sys, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

sys.path.insert(0, "/home/ma-xiuyuan/singtel_mesh")
from sg import Mesh, arcmd5

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.3.2"
BASE = "https://%s" % HOST
PW = "FACTORY_PASSWORD_HERE"

m = Mesh(HOST, "admin", PW)

def tok_from(text):
    mm = re.search(r'src="(data:image/gif;base64,[^"]+)"', text or "")
    return mm.group(1)[78:] if mm else None

# ---- 1. 登录 ----
t = m._token()
d = {"url": "", "name": arcmd5(arcmd5("admin") + t),
     "pws": arcmd5(arcmd5(PW) + t), "httoken": t}
r = m.s.post(BASE + "/login.cgi", data=d, timeout=10, allow_redirects=False)
loc = r.headers.get("Location", "")
print("① 登录 -> %s" % loc)
if loc != "/change_pwd.htm":
    sys.exit("   不是预期的 /change_pwd.htm，停")

print("   cookie原始:", r.headers.get("Set-Cookie","-"))

# ---- 2. 拿改密码页，看它长什么样 ----
r = m.s.get(BASE + "/change_pwd.htm", timeout=10, allow_redirects=False)
print("② GET /change_pwd.htm -> %s  %dB" % (r.status_code, len(r.text)))
print("   Location:", r.headers.get("Location", "-"))
nt = tok_from(r.text)
print("   页内有新 token:", (nt[:20] + "...") if nt else "无")
forms = re.findall(r'<form[^>]*action="([^"]*)"[^>]*>', r.text)
print("   form action:", forms)
inputs = re.findall(r'<input[^>]*name="([^"]*)"[^>]*>', r.text)
print("   input names:", inputs)
open("/tmp/change_pwd.htm", "w").write(r.text)

# ---- 3. 会话能读受保护页面吗 ----
for page in ["/index.htm", "/ssid.htm", "/device_name.htm", "/system_main.htm"]:
    rr = m.s.get(BASE + page, timeout=10, allow_redirects=False)
    L = rr.headers.get("Location", "")
    print("③ GET %-18s -> %s %s %dB" % (page, rr.status_code, ("->" + L) if L else "", len(rr.text)))
