#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测工厂复位端点是否免登录可达（只发无害空请求，不触发复位）。"""
import re, time
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

B = "https://192.168.3.2"
s = requests.Session()
s.verify = False
s.headers.update({
    "User-Agent": "Mozilla/5.0 Chrome/155.0",
    "Referer": B + "/factory_reset.htm",
    "Origin": B,
    "X-Requested-With": "XMLHttpRequest",
})


def tok():
    t = s.get(B + "/login.htm", timeout=8).text
    m = re.search(r'src="(data:image/gif;base64,[^"]+)"', t)
    return m.group(1)[78:] if m else None


print("=== 根目录动作端点的可达性 ===")
for ep in ["/apply_abstract.cgi", "/toplogy.cgi", "/factory_reset.cgi",
           "/reset.cgi", "/sys_reset.cgi", "/system_reset.cgi"]:
    tk = tok()
    try:
        r = s.post(B + ep, data={"httoken": tk, "cmd": "", "data": ""},
                   timeout=8, allow_redirects=False)
        print("  %-24s %s %6dB loc=%-16s %s"
              % (ep, r.status_code, len(r.text), r.headers.get("Location", "-"),
                 r.text[:60].replace("\n", " ")))
    except Exception as e:
        print("  %-24s %s" % (ep, type(e).__name__))

print()
print("=== 复位相关页面是否免登录 ===")
for p in ["/factory_reset.htm", "/reboot.htm", "/system_r.htm", "/system_main.htm"]:
    try:
        r = s.get(B + p, timeout=6, allow_redirects=False)
        print("  %-22s %s loc=%s" % (p, r.status_code, r.headers.get("Location", "-")))
    except Exception as e:
        print("  %-22s %s" % (p, type(e).__name__))
