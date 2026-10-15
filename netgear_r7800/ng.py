#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NETGEAR R7800 (Nighthawk X4S, 国行固件 V1.0.2.92PR) SOAP API —— 192.168.3.3

设备现状：以 AP 模式工作，IP 由主路由 (华为 Q2S) 的 DHCP 静态绑定发放。

接口全貌（探测方式：不存在的服务返回 404，存在的返回 401 —— 不需要密码就能枚举）：
    /soap/server_sa/                 SOAP 端点
    /currentsetting.htm              免认证！吐出固件/机型/区域等
    存在的服务：DeviceConfig:1  DeviceInfo:1  WLANConfiguration:1
                ParentalControl:1  AdvancedQoS:1  Time:1

    DeviceConfig:1 已知方法：
        SOAPLogin       登录，密码明文，成功返回 ResponseCode 000 + jwt_local cookie
        GetInfo         设备信息
        GetConfigInfo   返回整份配置（base64，加密，熵 7.95，改不了）
        Reboot          ⚠️ 立即重启设备——**没事别调**

没法改 LAN IP：SOAP 里没有 LANConfig 服务，Web UI 走 HTTP Basic 但用
admin/密码 拿不到（401）。所以 R7800 的 IP 只能靠主路由的 DHCP 绑定决定，
或者登它自己的网页 (http://192.168.3.3/) 手改。

用法：
    python3 ng.py info       # 设备信息（免认证的部分 + SOAP GetInfo）
    python3 ng.py probe      # 重新枚举 SOAP 服务
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET

import requests
import urllib3

urllib3.disable_warnings()

HOST = "192.168.3.3"
USER = "admin"
PW = "ROUTER_PASSWORD_HERE"
NS = "urn:NETGEAR-ROUTER:service:DeviceConfig:1"

KNOWN_SERVICES = ["DeviceConfig", "DeviceInfo", "WLANConfiguration",
                  "ParentalControl", "AdvancedQoS", "Time",
                  "LANConfig", "WANConfig", "Firewall", "QoS", "GuestNetwork"]
SAFE_METHODS = ["GetInfo", "GetConfigInfo"]      # 绝不能把 Reboot 放进自动探测！


class NG:
    def __init__(self, host=HOST, user=USER, pw=PW):
        self.host = host
        self.base = "http://%s" % host
        self.user, self.pw = user, pw
        self.s = requests.Session()

    def public_info(self):
        """currentsetting.htm 免认证，直接读"""
        return self.s.get(self.base + "/currentsetting.htm", timeout=8).text

    def soap(self, service, method, body="", timeout=10):
        env = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
               'SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
               '<SOAP-ENV:Header/><SOAP-ENV:Body>'
               '<M1:%s xmlns:M1="urn:NETGEAR-ROUTER:service:%s:1">%s</M1:%s>'
               '</SOAP-ENV:Body></SOAP-ENV:Envelope>') % (method, service, body, method)
        r = self.s.post(self.base + "/soap/server_sa/", data=env, timeout=timeout,
                        headers={"SOAPAction": "urn:NETGEAR-ROUTER:service:%s:1#%s" % (service, method),
                                 "Content-Type": 'text/xml; charset="utf-8"'})
        return r

    def login(self):
        body = "<Username>%s</Username><Password>%s</Password>" % (self.user, self.pw)
        r = self.soap("DeviceConfig", "SOAPLogin", body)
        code = self._code(r.text)
        if code != "000":
            raise RuntimeError("登录失败，ResponseCode=%s（密码错？）" % code)
        return True

    @staticmethod
    def _code(xml):
        m = re.search(r"<ResponseCode>(\d+)</ResponseCode>", xml)
        return m.group(1) if m else "?"

    def probe_services(self, names=KNOWN_SERVICES):
        """401=服务存在，404=不存在。不发密码就能枚举，且不触发任何副作用。"""
        out = {}
        for n in names:
            r = self.soap(n, "Probe", timeout=6)
            out[n] = self._code(r.text)
        return out


def cmd_info(ng):
    print("═══ 免认证 (/currentsetting.htm) ═══")
    print(ng.public_info().strip())
    print("\n═══ 登录并取 SOAP GetInfo ═══")
    ng.login()
    r = ng.soap("DeviceConfig", "GetInfo")
    print("HTTP", r.status_code)
    print(re.sub(r"\n\s*\n", "\n", r.text)[:1200])


def cmd_probe(ng):
    print("SOAP 服务枚举（401=存在 / 404=不存在）：")
    for n, c in ng.probe_services().items():
        tag = "  ← 存在" if c == "401" else ("  ← 需要先登录" if c == "000" else "")
        print("  %-20s %s%s" % (n, c, tag))


def main():
    ap = argparse.ArgumentParser(description="NETGEAR R7800 SOAP 客户端")
    ap.add_argument("cmd", choices=["info", "probe", "services"])
    ap.add_argument("--host", default=HOST)
    a = ap.parse_args()
    ng = NG(a.host)
    {"info": cmd_info, "probe": cmd_probe, "services": cmd_probe}[a.cmd](ng)


if __name__ == "__main__":
    main()
