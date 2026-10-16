#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改 3.2 的管理员密码。每个请求都用新鲜 token —— 这是之前崩溃的真正原因。"""
import os
import re, sys, time, base64
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, os.path.expanduser("~/singtel_mesh"))
from sg import Mesh, arcmd5

HOST = "192.168.3.2"; BASE = "https://%s" % HOST
OLD = "FACTORY_PASSWORD_HERE"; NEW = "ROUTER_PASSWORD_HERE"
CMD = sys.argv[1] if len(sys.argv) > 1 else "syncpasswdconfig2"

def encode(s):
    """设备自己的 encode()：每字符 +97，空格分隔（字典里的 'wg7005d' 是诱饵）"""
    return "".join("%d " % (ord(c) + 97) for c in s)

m = Mesh(HOST, "admin", OLD)
t = m._token()
r = m.s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False,
             data={"url": "", "name": arcmd5(arcmd5("admin") + t),
                   "pws": arcmd5(arcmd5(OLD) + t), "httoken": t})
print("① 登录 ->", r.headers.get("Location"))
if r.headers.get("Location") != "/change_pwd.htm":
    sys.exit("   没进强制改密码页，停手")

# ★ 新鲜 token
pg = m.s.get(BASE + "/change_pwd.htm", timeout=10)
TOK = re.search(r'src="(data:image/gif;base64,[^"]+)"', pg.text).group(1)[78:]
print("② 新鲜 token =", TOK)

payload = encode(NEW) if CMD.endswith("2") else (encode(OLD) + "?" + encode(NEW))
print("③ %s\n   data = %r" % (CMD, payload))

m.s.headers.update({"X-Requested-With": "XMLHttpRequest",
                    "Referer": BASE + "/change_pwd.htm", "Origin": BASE, "Accept": "*/*"})
try:
    rr = m.s.post(BASE + "/cgi-bin/toplogy.cgi", timeout=20, allow_redirects=False,
                  data={"httoken": TOK, "cmd": CMD, "data": payload})
    print("④ HTTP %s  body = %r" % (rr.status_code, rr.text[:200]))
except Exception as e:
    print("④ ✗ %r" % e)

print("\n⑤ 等设备重启，轮询登录...")
for i in range(20):
    time.sleep(6)
    for pwd, tag in ((NEW, "新密码"), (OLD, "旧密码")):
        try:
            mm = Mesh(HOST, "admin", pwd)
            tt = mm._token()
            rr = mm.s.post(BASE + "/login.cgi", timeout=6, allow_redirects=False,
                           data={"url": "", "name": arcmd5(arcmd5("admin") + tt),
                                 "pws": arcmd5(arcmd5(pwd) + tt), "httoken": tt})
            loc = rr.headers.get("Location", "?")
        except Exception as e:
            loc = "ERR"
        if tag == "新密码" and loc not in ("/loginpserr.htm", "ERR", "?"):
            print("   [%2d] ★ %s -> %s" % (i, tag, loc))
        elif tag == "旧密码":
            print("   [%2d] 新=%s  旧=%s" % (i, loc, loc))
    # 单独打印，避免上面覆盖
