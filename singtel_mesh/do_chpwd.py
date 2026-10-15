#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改管理密码 —— 完整复刻浏览器 change_pwd.htm 的流程。

  ① 登录（FACTORY_PASSWORD_HERE）                 -> /change_pwd.htm
  ② 从 change_pwd.htm 取【新鲜】token  <- 关键！之前崩就是因为用了已消耗的 token
  ③ POST toplogy.cgi  cmd=syncpasswdconfig2  data=encode(新密码)
  ④ 紧接着 POST login.exe  pws=encode(新密码)   <- 浏览器 subForm(tF2) 那步
  ⑤ 等设备重启，用新密码验证
"""
import re, sys, time, hashlib
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

HOST = "192.168.3.2"
BASE = "https://%s" % HOST
OLD = "FACTORY_PASSWORD_HERE"
NEW = sys.argv[1] if len(sys.argv) > 1 else "ROUTER_PASSWORD_HERE"


def arcmd5(x):
    return hashlib.sha512(hashlib.md5(x.encode()).hexdigest().encode()).hexdigest()


def encode(s):
    """设备自己的 encode()：每字符 +97，空格分隔（change_pwd.htm 里那段 packed 代码）"""
    return "".join("%d " % (ord(c) + 97) for c in s)


def gif_token(text):
    m = re.search(r'src="(data:image/gif;base64,[^"]+)"', text or "")
    return m.group(1)[78:] if m else None


s = requests.Session()
s.verify = False
s.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": BASE + "/login.htm", "Origin": BASE,
})

# ① 登录
t = s.get(BASE + "/login.htm", timeout=10).text
tk = gif_token(t)
r = s.post(BASE + "/login.cgi", timeout=12, allow_redirects=False, data={
    "url": "", "name": arcmd5(arcmd5("admin") + tk),
    "pws": arcmd5(arcmd5(OLD) + tk), "httoken": tk})
loc = r.headers.get("Location", "?")
print("① 登录 ->", loc)
if loc not in ("/change_pwd.htm", "/index.htm"):
    sys.exit("   登录失败，停手")

# ② 新鲜 token（从 change_pwd.htm）
pg = s.get(BASE + "/change_pwd.htm", timeout=10, allow_redirects=False)
TOK = gif_token(pg.text)
print("② 新鲜 token =", TOK, "->", __import__("base64").b64decode(TOK).decode())
if not TOK:
    sys.exit("   拿不到 token，停手")

s.headers.update({"X-Requested-With": "XMLHttpRequest",
                  "Referer": BASE + "/change_pwd.htm", "Accept": "*/*"})

# ③ 改密码
print("③ syncpasswdconfig2  data = %r" % encode(NEW))
try:
    r3 = s.post(BASE + "/cgi-bin/toplogy.cgi", timeout=25, allow_redirects=False,
                data={"httoken": TOK, "cmd": "syncpasswdconfig2", "data": encode(NEW)})
    print("   -> %s %r" % (r3.status_code, r3.text[:120]))
except Exception as e:
    print("   ✗ %r" % e)

# ④ 浏览器紧接着提交 tF2
print("④ login.exe  pws = encode(新密码)")
try:
    r4 = s.post(BASE + "/cgi-bin/login.exe", timeout=15, allow_redirects=False,
                data={"url": "", "name": "", "pws": encode(NEW), "httoken": TOK})
    print("   -> %s loc=%s" % (r4.status_code, r4.headers.get("Location", "-")))
except Exception as e:
    print("   （.exe 端点本来就会 reset 连接，属正常）%s" % type(e).__name__)

# ⑤ 等重启，验证
print("\n⑤ 等设备落盘/重启，然后验证 ...")
time.sleep(75)
for tag, pwd in (("新密码", NEW), ("旧密码", OLD)):
    for attempt in range(6):
        try:
            m = requests.Session(); m.verify = False
            m.headers.update({"User-Agent": s.headers["User-Agent"]})
            tt = gif_token(m.get(BASE + "/login.htm", timeout=8).text)
            if not tt:
                time.sleep(10); continue
            rr = m.post(BASE + "/login.cgi", timeout=8, allow_redirects=False, data={
                "url": "", "name": arcmd5(arcmd5("admin") + tt),
                "pws": arcmd5(arcmd5(pwd) + tt), "httoken": tt})
            print("   %s -> %s" % (tag, rr.headers.get("Location", "?")))
            break
        except Exception as e:
            time.sleep(10)
    else:
        print("   %s -> 设备无响应" % tag)
