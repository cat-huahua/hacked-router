#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计数已爆表，试候选密码不再有额外代价。顺便验证锁是否真的拦登录。"""
import os
import re, sys, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
sys.path.insert(0, os.path.expanduser("~/singtel_mesh"))
from sg import Mesh, arcmd5

BASE = "https://192.168.3.2"

def enc(s): return "".join("%d " % (ord(c) + 97) for c in s)

CANDS = [
    ("ROUTER_PASSWORD_HERE", "新密码"),
    ("FACTORY_PASSWORD_HERE", "旧密码"),
    (enc("ROUTER_PASSWORD_HERE").strip(), "encode(新) 去尾空格"),
    (enc("ROUTER_PASSWORD_HERE"), "encode(新) 带尾空格"),
    (enc("FACTORY_PASSWORD_HERE").strip(), "encode(旧)"),
    ("ROUTER_PASSWORD_HERE_NO_SYMBOL", "去掉末尾符号"),
    ("admin", "常见默认"),
    ("__definitely_wrong__", "★ 对照组（必然错）"),
]

seen = {}
for pwd, tag in CANDS:
    try:
        m = Mesh("192.168.3.2", "admin", pwd)
        t = m._token()
        r = m.s.post(BASE + "/login.cgi", timeout=8, allow_redirects=False,
                     data={"url": "", "name": arcmd5(arcmd5("admin") + t),
                           "pws": arcmd5(arcmd5(pwd) + t), "httoken": t})
        loc = r.headers.get("Location", "?")
        seen.setdefault(loc, []).append(tag)
        mark = "  ★★★ 成功！" if loc == "/index.htm" else ""
        print("%-26s -> %s   (%s)%s" % (repr(pwd)[:26], loc, tag, mark), flush=True)
        if loc == "/index.htm":
            print("\n密码就是:", pwd); break
    except Exception as e:
        print("%-26s ERR %s (%s)" % (repr(pwd)[:26], type(e).__name__, tag), flush=True)
    time.sleep(1)

print()
print("=== 结果归类 ===")
for loc, tags in seen.items():
    print("  %-20s <- %s" % (loc, ", ".join(tags)))
