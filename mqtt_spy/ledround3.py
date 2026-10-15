#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第三轮：带上设备身份（_device_id / _sn），这是前两轮漏掉的关键字段。"""
import time, sys, subprocess, json
sys.path.insert(0, "/home/ma-xiuyuan/mqtt_spy")
from pub import connect, publish

DEV = "AABBCC000001"
SN = "J000000J00001"
AD = "devices/%s/adornment" % DEV
DS = "devices/%s/desired_state" % DEV
DI = "devices/%s/direct" % DEV

CANDS = [
    (AD, "/accesspoint?_adornment&_device_id=%s&_led_glbcfg=0" % DEV),
    (AD, "/accesspoint?_adornment&_device_id=%s&_led_onoff=0" % DEV),
    (AD, "/accesspoint?_device_id=%s&_led_glbcfg=0" % DEV),
    (AD, "/accesspoint?_adornment&_sn=%s&_led_glbcfg=0" % SN),
    (AD, "/accesspoint?_adornment&_led=0"),
    (AD, "/accesspoint?_adornment&_value=0"),
    (AD, json.dumps({"state": {"desired": {"led_glbcfg": 0}}})),
    (DS, "/accesspoint?_adornment&_device_id=%s&_led_glbcfg=0" % DEV),
    (DS, json.dumps({"state": {"desired": {"led_glbcfg": 0}}})),
    (DI, "/accesspoint?_adornment&_device_id=%s&_led_glbcfg=0" % DEV),
]


def connected():
    try:
        out = subprocess.run(["ss", "-tn"], capture_output=True, text=True, timeout=5).stdout
        return "192.168.3.2" in out and ":8883" in out
    except Exception:
        return False


print("等设备连上...", flush=True)
end = time.time() + 600
while time.time() < end:
    if connected():
        print("  已连上 ✓\n", flush=True)
        break
    time.sleep(5)
else:
    print("  ✗ 超时"); sys.exit(1)

time.sleep(3)
s = connect("ledr3")
for i, (topic, payload) in enumerate(CANDS, 1):
    print("【第3轮 第 %d 发】%s  主题=%s" % (i, time.strftime("%H:%M:%S"), topic.split("/")[-1]), flush=True)
    print("          %s" % payload, flush=True)
    publish(s, topic, payload, 1)
    time.sleep(12)

print("\n第三轮发完。", flush=True)
s.close()
