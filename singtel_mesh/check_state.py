#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重置后只读检查：不登录、不试密码。读 wait_secs 和 login_counter。"""
import re, time, sys
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

B = "https://192.168.3.2"
s = requests.Session()
s.verify = False
s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155.0", "Referer": B + "/login.htm"})


def tok():
    t = s.get(B + "/login.htm", timeout=8).text
    m = re.search(r'src="(data:image/gif;base64,[^"]+)"', t)
    return m.group(1)[78:] if m else None


# 1. 等设备起来
print("等设备响应...", flush=True)
for i in range(30):
    try:
        r = s.get(B + "/login.htm", timeout=5)
        if r.status_code == 200:
            print("  设备已在线（第 %d 次探测）" % (i + 1))
            break
    except Exception as e:
        print("  [%d] %s" % (i, type(e).__name__), flush=True)
    time.sleep(6)
else:
    print("  超时"); sys.exit(1)

# 2. wait_secs
t = s.get(B + "/login.htm", timeout=8).text
m = re.search(r'wait_secs\s*=\s*parseInt\("(-?\d+)"\)', t)
print()
print("★ wait_secs =", m.group(1) if m else "(读不到)")
if m and m.group(1) != "0":
    print("  ✗ 倒计时没归零，不试登录"); sys.exit(1)

# 3. login_counter（免登录的 cgi_init.js）
print()
for name in ["init", "login"]:
    for attempt in range(3):
        tk = tok()
        r = s.get("%s/cgi/cgi_%s.js?_tn=%s&_t=%d" % (B, name, tk, int(time.time() * 1000)),
                  timeout=8, allow_redirects=False)
        if r.status_code == 200:
            print("── cgi_%s.js ──" % name)
            print(r.text.strip())
            break
        time.sleep(1)
    else:
        print("── cgi_%s.js 取不到（%s）" % (name, r.status_code))
