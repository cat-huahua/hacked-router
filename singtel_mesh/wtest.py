#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单发实验：闸门会话能否写 toplogy.cgi。只发一次，绝不重试。"""
import os
import re, sys, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, os.path.expanduser("~/singtel_mesh"))
from sg import Mesh, arcmd5

HOST = "192.168.3.2"; BASE = "https://%s" % HOST; PW = "FACTORY_PASSWORD_HERE"
m = Mesh(HOST, "admin", PW)

t = m._token()
m.s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False,
         data={"url": "", "name": arcmd5(arcmd5("admin") + t),
               "pws": arcmd5(arcmd5(PW) + t), "httoken": t})
print("① 登录 -> OK")

# 新鲜 token（从 change_pwd.htm 的 GIF 取，和浏览器一致）
r = m.s.get(BASE + "/change_pwd.htm", timeout=10)
TOK = re.search(r'src="(data:image/gif;base64,[^"]+)"', r.text).group(1)[78:]
print("② token =", TOK)

# 浏览器 jQuery $.ajax 会带这些头
m.s.headers.update({
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE + "/change_pwd.htm",
    "Origin": BASE,
    "Accept": "*/*",
})

print("③ 单发 POST /cgi-bin/toplogy.cgi  cmd=syncdevicename (只此一次)")
try:
    rr = m.s.post(BASE + "/cgi-bin/toplogy.cgi", timeout=15, allow_redirects=False,
                  data={"httoken": TOK, "cmd": "syncdevicename",
                        "data": "AA:BB:CC:00:00:02?$[+NODE_NAME_2"})
    print("   HTTP %s  Location=%s" % (rr.status_code, rr.headers.get("Location", "-")))
    print("   body(%dB): %r" % (len(rr.text), rr.text[:300]))
except Exception as e:
    print("   ✗ %r" % e)
