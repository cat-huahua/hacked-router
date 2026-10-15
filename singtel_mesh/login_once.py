#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重置后【只登一次】。先等设备稳定，核对 wait_secs=0，再单发一次登录。"""
import re, time, sys, json, pickle
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

B = "https://192.168.3.2"
USER = "admin"
PW = sys.argv[1] if len(sys.argv) > 1 else "FACTORY_PASSWORD_HERE"


def arcmd5(x):
    import hashlib
    return hashlib.sha512(hashlib.md5(x.encode()).hexdigest().encode()).hexdigest()


s = requests.Session()
s.verify = False
s.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": B + "/login.htm",
    "Origin": B,
})

# ---- 1. 等设备稳定（连续 3 次成功响应）----
print("等设备稳定（需连续 3 次正常）...", flush=True)
ok = 0
deadline = time.time() + 300
while time.time() < deadline and ok < 3:
    try:
        r = s.get(B + "/login.htm", timeout=6)
        if r.status_code == 200 and len(r.text) > 1000:
            ok += 1
            print("  稳定计数 %d/3 (%.0fs)" % (ok, time.time() - (deadline - 300)), flush=True)
        else:
            ok = 0; print("  http=%s" % r.status_code, flush=True)
    except Exception as e:
        ok = 0
        print("  %s" % type(e).__name__, flush=True)
    time.sleep(8)
if ok < 3:
    print("✗ 设备一直不稳定，停手"); sys.exit(1)

# ---- 2. 核对 wait_secs ----
t = s.get(B + "/login.htm", timeout=8).text
m = re.search(r'wait_secs\s*=\s*parseInt\("(-?\d+)"\)', t)
w = m.group(1) if m else None
print()
print("★ wait_secs =", w, flush=True)
if w != "0":
    print("✗ 倒计时不是 0（%s），不登录，停手" % w); sys.exit(1)

print("✓ 倒计时为 0，可以安全登录", flush=True)

# ---- 3. 取 token，单发登录 ----
m = re.search(r'src="(data:image/gif;base64,[^"]+)"', t)
tok = m.group(1)[78:]
print("  token =", tok, flush=True)

r = s.post(B + "/login.cgi", timeout=12, allow_redirects=False, data={
    "url": "", "name": arcmd5(arcmd5(USER) + tok),
    "pws": arcmd5(arcmd5(PW) + tok), "httoken": tok})
loc = r.headers.get("Location", "?")
print()
print("★★ 登录 %s/%s -> %s" % (USER, PW, loc), flush=True)

if loc in ("/index.htm", "/change_pwd.htm"):
    print("★★★★★ 登录成功！会话已建立", flush=True)
    pickle.dump(s.cookies, open("/tmp/mesh_session.pkl", "wb"))
    open("/tmp/mesh_session.txt", "w").write("ok")
else:
    print("✗ 这次没成功（Location=%s）。已用掉 1 次，最多还剩 9 次。" % loc, flush=True)
    # 立刻回读倒计时，看有没有被加罚
    t2 = s.get(B + "/login.htm", timeout=8).text
    m2 = re.search(r'wait_secs\s*=\s*parseInt\("(-?\d+)"\)', t2)
    print("  登录后 wait_secs =", m2.group(1) if m2 else "?", flush=True)
