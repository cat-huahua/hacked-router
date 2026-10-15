#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锁已清除，可以安全验证候选密码。每次之间检查 wait_secs，任何非 0 立刻停手。"""
import re, sys, time, hashlib
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

BASE = "https://192.168.3.2"
NEW = "ROUTER_PASSWORD_HERE"


def arcmd5(x):
    return hashlib.sha512(hashlib.md5(x.encode()).hexdigest().encode()).hexdigest()


def enc(s):
    return "".join("%d " % (ord(c) + 97) for c in s)


CANDS = [
    enc(NEW),                 # 带尾空格
    enc(NEW).strip(),         # 去尾空格
    enc(NEW).replace(" ", ""),  # 完全无空格
    "ROUTER_PASSWORD_HERE_NO_SYMBOL",   # 去掉末尾符号
]


def wait_secs():
    s = requests.Session(); s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155.0"})
    t = s.get(BASE + "/login.htm", timeout=8).text
    m = re.search(r'wait_secs\s*=\s*parseInt\("(-?\d+)"\)', t)
    return int(m.group(1)) if m else None


def try_pw(pwd):
    s = requests.Session(); s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 Chrome/155.0"})
    t = s.get(BASE + "/login.htm", timeout=8).text
    m = re.search(r'src="(data:image/gif;base64,[^"]+)"', t)
    if not m:
        return "NO_TOKEN"
    tok = m.group(1)[78:]
    r = s.post(BASE + "/login.cgi", timeout=10, allow_redirects=False, data={
        "url": "", "name": arcmd5(arcmd5("admin") + tok),
        "pws": arcmd5(arcmd5(pwd) + tok), "httoken": tok})
    return r.headers.get("Location", "?")


print("起始 wait_secs =", wait_secs())
for c in CANDS:
    w = wait_secs()
    print()
    print("wait_secs=%s  试: %r" % (w, c[:60]))
    if w != 0:
        print("  ✗ 倒计时不是 0，停手（避免再次锁死）"); break
    loc = try_pw(c)
    print("  -> %s" % loc)
    if loc in ("/index.htm", "/change_pwd.htm"):
        print("  ★★★★★★★ 成功！密码就是: %r" % c)
        break
    time.sleep(2)
else:
    print("\n候选都试完了。")
print()
print("结束 wait_secs =", wait_secs())
