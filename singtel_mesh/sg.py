#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Singtel Mesh (Arcadyan 固件 v6.02.00) 本地管理 API —— 192.168.3.2 等节点

登录算法（从设备自己的 js/global.js 逆出，已用设备自带 JS 在 Node 里逐字节验证）：
    token  = 页面里那张 1x1 透明 GIF 的 data URI，从第 78 个字符起
    httoken = token                       ← 表单必须带这个字段，漏了就永远登录失败
    name    = ArcMD5( ArcMD5(用户名) + token )
    pws     = ArcMD5( ArcMD5(密码)   + token )
    ArcMD5(x) = SHA-512_hex( MD5_hex(x) )

坑：
  · 必须带 Referer / User-Agent，否则服务器不收（会 302 回 /login.htm）
  · token 是一次性的，每次请求都要重新从页面里取
  · Set-Cookie 是畸形的（`HttpOnly;max-age=3600`，没有 name=value），
    所以 requests 的 cookies 迭代会抛异常 —— 会话靠 token 而不是 cookie
  · 设备时钟停在 2016 年，没同步 NTP，别被响应里的 Date 骗了

用法：
    python3 sg.py pages                 # 列出全部管理页面
    python3 sg.py get lan1.htm          # 取某个页面
    python3 sg.py status                # 打印设备状态页要点
"""
import argparse
import hashlib
import re
import sys
import time

import requests
import urllib3

urllib3.disable_warnings()

HOST = "192.168.3.2"

# 拓扑（实测 2026-10-14）：
#   3.2  控制器，唯一暴露管理 UI 的节点
#   3.20 / 3.21 / 3.22  卫星节点 —— **没有独立管理界面**，
#                       所有路径（/ /login.htm /index.htm /menu.htm ...）
#                       一律 302 跳到 https://192.168.3.2/
#                       它们虽然也开 443（mesh 回程用），但浏览器访问全甩给控制器。
#                       管理它们只能从 3.2 进。
# 未攻破：控制器上的拓扑 CGI（status_lan_device.htm 里 CGIs=["toplogy_info"]，
#   do_jload 会带 ?_tn=<token>&_t=<ts> 去取），但 /cgi-bin/* 一律被服务器
#   connection reset，GET/POST、带不带 token 都一样。想要拓扑数据得想别的办法。
USER = "admin"
PW = "ROUTER_PASSWORD_HERE"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/155.0.0.0 Safari/537.36 Edg/155.0.0.0")

# js/menu.js 里的完整页面表
PAGES = {
    "status":               "status.htm",
    "status_lan_device":    "status_lan_device.htm",
    "ssid":                 "ssid.htm",
    "lan":                  "lan1.htm",
    "led":                  "led_main.htm",
    "wireless_wps":         "wireless_WPS.htm",
    "system":               "system_main.htm",
    "device_name":          "device_name.htm",
    "system_p":             "system_p.htm",
    "discs":                "discs.htm",
    "system_r":             "system_r.htm",
    "security_log":         "security_log.htm",
    "advance":              "advance.htm",
}

POST_TARGETS = {
    "lan1.htm":       "/cgi-bin/setup_lan.exe",
    "ssid.htm":       "/cgi-bin/setup_wlan.exe",
    "device_name.htm": "/cgi-bin/setup_device_name.exe",
}


def arcmd5(x):
    """设备自己的 ArcMD5：SHA-512_hex(MD5_hex(x))"""
    return hashlib.sha512(hashlib.md5(x.encode()).hexdigest().encode()).hexdigest()


class Mesh:
    def __init__(self, host=HOST, user=USER, pw=PW):
        self.host = host
        self.base = "https://%s" % host
        self.user, self.pw = user, pw
        self.s = requests.Session()
        self.s.verify = False
        self.s.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Referer": self.base + "/login.htm",
            "Origin": self.base,
        })

    def _token(self):
        """从页面里取出一次性 token（那张 1x1 GIF 的 data URI，[78:]）"""
        r = self.s.get(self.base + "/login.htm", timeout=10)
        m = re.search(r'src="(data:image/gif;base64,[^"]+)"', r.text)
        if not m:
            raise RuntimeError("登录页里找不到 token")
        return m.group(1)[78:]

    def login(self):
        self._token()                      # 先热一下会话
        tok = self._token()
        d = {
            "url": "",
            "name": arcmd5(arcmd5(self.user) + tok),
            "pws": arcmd5(arcmd5(self.pw) + tok),
            "httoken": tok,                # ← 少了这个必失败
        }
        r = self.s.post(self.base + "/login.cgi", data=d, timeout=10, allow_redirects=False)
        loc = r.headers.get("Location", "")
        if loc != "/index.htm":
            raise RuntimeError("登录失败，Location=%s（检查密码）" % loc)
        return True

    def get(self, page):
        return self.s.get("%s/%s" % (self.base, page), timeout=15)

    # ------------------------------------------------------------------
    # ★ 真正能用的接口（2026-10-14 实测）
    #
    #   规律：**`.exe` 一律 connection reset**（curl / requests / 真浏览器 fetch 都一样），
    #         但 `*.cgi` 和 `/cgi/*.js` 完全正常。
    #   所以别再照表单的 action="/cgi-bin/xxx.exe" 去打了。
    #
    #   读数据：GET /cgi/cgi_<CGI名>.js?_tn=<token>&_t=<毫秒>&_=<毫秒+1>
    #           token 从当前页那张 1x1 GIF 的 data URI [78:] 取，**一次性**，
    #           登录会把它消耗掉 —— 登录后要么重新加载页面，要么重新取。
    #           返回的是 JS（addCfg("名","id","值") 这种），用 dataType:"script" 跑。
    #
    #   写数据：POST /cgi-bin/toplogy.cgi
    #           httoken=<token>  cmd=syncdevicename  data=<device_mac>?$[+<新名字>
    #           成功返回 "ok"
    #           ⚠️ data 里的 device_mac 是 mesh **内部** MAC，不是网卡 MAC！
    #              用网卡 MAC 打进去也返回 "ok"，但**不生效**（这个坑踩过）
    # ------------------------------------------------------------------
    def cgi(self, name, token=None):
        """读 /cgi/cgi_<name>.js，返回原始 JS 文本"""
        tok = token or self._token()
        ts = int(time.time() * 1000)
        u = "%s/cgi/cgi_%s.js?_tn=%s&_t=%d&_=%d" % (self.base, name, tok, ts, ts + 1)
        return self.s.get(u, timeout=15)

    @staticmethod
    def inner_mac(lan_mac):
        """网卡 MAC -> mesh 内部 MAC：**最后一个字节 +1**

        实测（2026-10-14）：
            主节点网卡 AA:BB:CC:00:00:01  ->  内部 D4:86:60:B0:51:67
            用网卡 MAC 打 syncdevicename 也返回 "ok"，但**名字纹丝不动**。
            这是最大的坑：接口不报错，静默失败。
        """
        p = lan_mac.upper().split(":")
        p[5] = "%02X" % ((int(p[5], 16) + 1) & 0xFF)
        return ":".join(p)

    def rename_node(self, lan_mac, new_name):
        """按网卡 MAC 重命名节点（自动换算内部 MAC）。

        ⚠️ 会触发整个 mesh 同步/重启 —— 主控会短暂失联几十秒，属正常。
        ⚠️ 只有主节点能用 /cgi/cgi_upnp_main.js 的 friendly_name 读回验证；
           卫星（3.20/3.21/3.22）没有读回通道，只能去网页上看。
        """
        return self.syncdevicename(self.inner_mac(lan_mac), new_name)

    def syncdevicename(self, device_mac, new_name, token=None):
        """底层：device_mac 必须是**内部** MAC，传网卡 MAC 会静默不生效。"""
        tok = token or self._token()
        return self.s.post(self.base + "/cgi-bin/toplogy.cgi",
                           data={"httoken": tok, "cmd": "syncdevicename",
                                 "data": "%s?$[+%s" % (device_mac, new_name)},
                           timeout=15, allow_redirects=False)

    def friendly_name(self):
        """读主节点当前名字（唯一能验证重命名结果的地方）"""
        m = re.search(r'friendly_name",\s*"[0-9]+",\s*"([^"]*)"', self.cgi("upnp_main").text)
        return m.group(1) if m else None

    def post(self, page, fields):
        target = POST_TARGETS.get(page, "/cgi-bin/setup_lan.exe")
        return self.s.post(self.base + target, data=fields, timeout=15, allow_redirects=False)


def cmd_pages(m):
    print("%-22s %s" % ("名称", "文件"))
    for k, v in PAGES.items():
        print("  %-20s %s" % (k, v))


def cmd_get(m, page):
    r = m.get(page)
    print("HTTP %s  %d 字节" % (r.status_code, len(r.content)))
    print(r.text)


def cmd_status(m):
    h = m.get(PAGES["status"]).text
    txt = re.sub(r"<script.*?</script>", " ", h, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    print(" ".join(txt.split())[:1500])


def main():
    ap = argparse.ArgumentParser(description="Singtel Mesh (Arcadyan) 管理接口")
    ap.add_argument("cmd", choices=["pages", "get", "status"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--host", default=HOST)
    a = ap.parse_args()

    m = Mesh(a.host)
    m.login()
    print("  ✓ 登录 %s 成功\n" % a.host)
    {"pages": lambda: cmd_pages(m),
     "get":   lambda: cmd_get(m, a.arg or PAGES["status"]),
     "status": lambda: cmd_status(m)}[a.cmd]()


if __name__ == "__main__":
    main()
