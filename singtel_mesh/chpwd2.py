#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整复刻浏览器改密码流程（change_pwd.htm）：
   ① 登录  ② 取新鲜 token  ③ syncpasswdconfig2  ④ 再 POST login.exe 提交 encoded 新密码
"""
import os
import re, sys, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, os.path.expanduser("~/singtel_mesh"))
from sg import Mesh, arcmd5

BASE = "https://192.168.3.2"
OLD = "FACTORY_PASSWORD_HERE"
NEW = sys.argv[1] if len(sys.argv) > 1 else "ROUTER_PASSWORD_HERE"

def encode(s):
    return "".join("%d " % (ord(c) + 97) for c in s)

m = Mesh("192.168.3.2", "admin", OLD)
t = m._token()
r = m.s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False,
             data={"url": "", "name": arcmd5(arcmd5("admin") + t),
                   "pws": arcmd5(arcmd5(OLD) + t), "httoken": t})
print("① 登录 ->", r.headers.get("Location"), flush=True)
if r.headers.get("Location") not in ("/change_pwd.htm", "/index.htm"):
    print("   旧密码登不进，停"); sys.exit(1)

pg = m.s.get(BASE + "/change_pwd.htm", timeout=10, allow_redirects=False)
if pg.status_code != 200:
    pg = m.s.get(BASE + "/index.htm", timeout=10)
TOK = re.search(r'src="(data:image/gif;base64,[^"]+)"', pg.text).group(1)[78:]
print("② token =", TOK, flush=True)

m.s.headers.update({"X-Requested-With": "XMLHttpRequest",
                    "Referer": BASE + "/change_pwd.htm", "Origin": BASE, "Accept": "*/*"})

# ③ 改密码
rr = m.s.post(BASE + "/cgi-bin/toplogy.cgi", timeout=20, allow_redirects=False,
              data={"httoken": TOK, "cmd": "syncpasswdconfig2", "data": encode(NEW)})
print("③ syncpasswdconfig2 -> %s %r" % (rr.status_code, rr.text[:100]), flush=True)

# ④ 浏览器紧接着提交 tF2 -> login.exe（pws 用 encode 后的新密码）
try:
    r4 = m.s.post(BASE + "/cgi-bin/login.exe", timeout=20, allow_redirects=False,
                  data={"url": "", "name": "", "pws": encode(NEW), "httoken": TOK})
    print("④ login.exe -> %s loc=%s %r" % (r4.status_code, r4.headers.get("Location", "-"),
                                            r4.text[:100]), flush=True)
except Exception as e:
    print("④ login.exe ✗ %r（.exe 可能本来就 reset 连接）" % e, flush=True)

print("\n⑤ 等 90 秒让设备落盘/重启，再验...", flush=True)
time.sleep(90)
for pwd in (NEW, OLD):
    try:
        mm = Mesh("192.168.3.2", "admin", pwd); tt = mm._token()
        r5 = mm.s.post(BASE + "/login.cgi", timeout=8, allow_redirects=False,
                       data={"url": "", "name": arcmd5(arcmd5("admin") + tt),
                             "pws": arcmd5(arcmd5(pwd) + tt), "httoken": tt})
        print("   %-12s -> %s" % (pwd, r5.headers.get("Location", "?")), flush=True)
        break
    except Exception as e:
        print("   %-12s 离线 %s" % (pwd, type(e).__name__), flush=True)
