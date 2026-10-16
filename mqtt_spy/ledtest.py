#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等设备连上 -> 往三个命令主题各发一轮 LED 候选格式 -> 观察设备反应"""
import os
import time, sys, subprocess
sys.path.insert(0, os.path.expanduser("~/mqtt_spy"))
from pub import connect, publish

DEV = "AABBCC000001"
LOG = os.path.expanduser("~/mqtt_spy/spy.log")

def connected():
    try:
        out = subprocess.run(["ss", "-tn"], capture_output=True, text=True, timeout=5).stdout
        return ":8883" in out and "192.168.3.2:" in out
    except Exception:
        return False

print("等设备连上 broker...", flush=True)
end = time.time() + 900
while time.time() < end:
    if connected():
        print("  设备已连上 ✓", flush=True)
        break
    time.sleep(5)
else:
    print("  ✗ 超时"); sys.exit(1)

time.sleep(5)
s = connect("ledtest")

TESTS = [
    ("devices/%s/adornment" % DEV,     "/accesspoint?_adornment&_led_glbcfg=1"),
    ("devices/%s/adornment" % DEV,     "/accesspoint?_adornment&_led_glbcfg=0"),
    ("devices/%s/adornment" % DEV,     "/accesspoint?_adornment&_led_glbcfg=2"),
    ("devices/%s/adornment" % DEV,     "/accesspoint?_adornment&_led_onoff=1"),
    ("devices/%s/adornment" % DEV,     "/accesspoint?_adornment&_color=FF0000"),
    ("devices/%s/direct" % DEV,        "/accesspoint?_syncledconfig&_led_glbcfg=1"),
    ("devices/%s/direct" % DEV,        "/accesspoint?_ledbrightness&_data=1"),
    ("devices/%s/desired_state" % DEV, "/accesspoint?_adornment&_led_glbcfg=1"),
]
for topic, payload in TESTS:
    print("\n>>> 发到 %s\n    %s" % (topic, payload), flush=True)
    publish(s, topic, payload, 1)
    time.sleep(9)
    try:
        with open(LOG) as f:
            tail = f.read()[-800:]
        for line in tail.splitlines():
            if "PUBLISH" in line and "127.0.0.1" not in line:
                print("    设备回话: %s" % line[-200:], flush=True)
    except Exception:
        pass

print("\n全部发完。看灯变了吗？", flush=True)
s.close()
