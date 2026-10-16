#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""恢复出厂后的最终配置：
   ① syncwificonfig —— SSID / WiFi密码 / 信道 11+153（用 good_20261014.json 作底）
   ② syncdevicename —— 四个节点名
   登录后 /change_pwd.htm 也算成功（闸门只拦 .htm 页面，写接口可用）
"""
import json, re, sys, time, hashlib
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

HOST = "192.168.3.2"
BASE = "https://%s" % HOST
USER, PW = "admin", "FACTORY_PASSWORD_HERE"
CH24, CH5 = "11", "153"

NODES = [
    ("AA:BB:CC:00:00:01", "NODE_NAME_1", "3.2  主控"),
    ("AA:BB:CC:00:00:02", "NODE_NAME_2", "3.20 节点2"),
    ("AA:BB:CC:00:00:03", "NODE_NAME_3", "3.21 节点3"),
    ("AA:BB:CC:00:00:04", "NODE_NAME_4", "3.22 节点4"),
]


def arcmd5(x):
    return hashlib.sha512(hashlib.md5(x.encode()).hexdigest().encode()).hexdigest()


def inner_mac(lan):
    p = lan.upper().split(":")
    p[5] = "%02X" % ((int(p[5], 16) + 1) & 0xFF)
    return ":".join(p)


s = requests.Session()
s.verify = False
s.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": BASE + "/login.htm", "Origin": BASE,
})


def gif_token(text):
    m = re.search(r'src="(data:image/gif;base64,[^"]+)"', text or "")
    return m.group(1)[78:] if m else None


# ---------- ① 登录 ----------
t = s.get(BASE + "/login.htm", timeout=10).text
tok = gif_token(t)
if not tok:
    sys.exit("拿不到 token")
r = s.post(BASE + "/login.cgi", timeout=12, allow_redirects=False, data={
    "url": "", "name": arcmd5(arcmd5(USER) + tok),
    "pws": arcmd5(arcmd5(PW) + tok), "httoken": tok})
loc = r.headers.get("Location", "?")
print("① 登录 -> %s" % loc)
if loc not in ("/index.htm", "/change_pwd.htm"):
    sys.exit("   登录失败，停手")

# ---------- ② 无线配置 ----------
print("\n② 无线配置")
cfg = json.load(open("/home/ma-xiuyuan/singtel_mesh/good_20261014.json"))
wps_index = "1" if cfg.get("wps_enable", "0") == "1" else "0"
fields = [
    cfg.get("24gname0", ""), cfg.get("5gname0", ""),
    cfg.get("24gbcast0", "0"), cfg.get("5gbcast0", "0"),
    cfg.get("24gsecurity_mode0", "WPA2PSK"), cfg.get("5gsecurity_mode0", "WPA2PSK"),
    cfg.get("24gwpapsk0", ""), cfg.get("5gwpapsk0", ""),
    wps_index, CH24, CH5,
    cfg.get("24gbandwidth", "0"), cfg.get("24gcoexistence", "0"), cfg.get("ldpc_24g", "0"),
    cfg.get("5gbandwidth", "0"), cfg.get("5gcoexistence", "0"), cfg.get("5gvhtBW", "0"),
]
payload = "?$[+".join(fields)
labels = ["2.4G SSID", "5G SSID", "2.4G bcast", "5G bcast", "2.4G sec", "5G sec",
          "2.4G psk", "5G psk", "wps", "★2.4G ch", "★5G ch", "24g bw", "24g coex",
          "ldpc", "5g bw", "5g coex", "5g vht"]
for lb, v in zip(labels, fields):
    print("   %-12s = %r" % (lb, v))

m = requests.Session()
m.verify = False
m.headers.update(s.headers)
m.cookies.update(s.cookies)
pg = m.get(BASE + "/change_pwd.htm", timeout=10, allow_redirects=False)
if pg.status_code != 200:
    pg = m.get(BASE + "/login.htm", timeout=10)
tok2 = gif_token(pg.text)
m.headers.update({"X-Requested-With": "XMLHttpRequest",
                  "Referer": BASE + "/change_pwd.htm", "Accept": "*/*"})
r2 = m.post(BASE + "/cgi-bin/toplogy.cgi", timeout=25, allow_redirects=False,
            data={"httoken": tok2, "cmd": "syncwificonfig", "data": payload})
print("\n   写入返回: %r" % r2.text.strip()[:100])
if r2.text.strip() == "ok_wifi":
    print("   ★★★ 无线配置写入成功！")
else:
    print("   ✗ 不是 ok_wifi")

# ---------- ③ 节点名 ----------
print("\n③ 节点名")
time.sleep(20)                      # 给 mesh 一点同步时间
for lan, name, label in NODES:
    try:
        pg = m.get(BASE + "/change_pwd.htm", timeout=10, allow_redirects=False)
        tk = gif_token(pg.text) or gif_token(m.get(BASE + "/login.htm", timeout=10).text)
        rr = m.post(BASE + "/cgi-bin/toplogy.cgi", timeout=20, allow_redirects=False,
                    data={"httoken": tk, "cmd": "syncdevicename",
                          "data": "%s?$[+%s" % (inner_mac(lan), name)})
        print("   %-16s -> %-16s %s" % (label, name, rr.text.strip()))
    except Exception as e:
        print("   %-16s ✗ %s" % (label, str(e)[:60]))
    time.sleep(3)

print("\n完成。")
