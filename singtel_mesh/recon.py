#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re, sys, time, base64
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, "/home/ma-xiuyuan/singtel_mesh")
from sg import Mesh, arcmd5

HOST = "192.168.3.2"; BASE = "https://%s" % HOST; PW = sys.argv[1] if len(sys.argv)>1 else "FACTORY_PASSWORD_HERE"
m = Mesh(HOST, "admin", PW)

def fresh():
    r = m.s.get(BASE + "/change_pwd.htm", timeout=10)
    mm = re.search(r'src="(data:image/gif;base64,[^"]+)"', r.text or "")
    return (mm.group(1)[78:] if mm else None), r

t = m._token()
m.s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False,
         data={"url": "", "name": arcmd5(arcmd5("admin") + t),
               "pws": arcmd5(arcmd5(PW) + t), "httoken": t})
print("① 登录 OK (%s)" % PW)

print("② 每个请求配一个新 token，读 /cgi/cgi_*.js：")
for name in ["toplogy_info","wifi","wireless_wps","device_name","status","lan",
             "system","autologout","login","sysinfo","device"]:
    tok, pg = fresh()
    if not tok:
        print("   %-14s 拿不到 token (page %dB)" % (name, len(pg.text))); continue
    ts = int(time.time() * 1000)
    u = "%s/cgi/cgi_%s.js?_tn=%s&_t=%d" % (BASE, name, tok, ts)
    try:
        rr = m.s.get(u, timeout=8, allow_redirects=False)
        b = rr.text
        print("   %-14s %s %5dB  %s" % (name, rr.status_code, len(b),
              ("->"+rr.headers["Location"]) if rr.headers.get("Location") else b[:100].replace("\n"," ")))
    except Exception as e:
        print("   %-14s ERR %r" % (name, e))
