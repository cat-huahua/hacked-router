#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二轮：如果查询串格式全军覆没，改试 JSON 格式。"""
import time, sys, subprocess, json
sys.path.insert(0, "/home/ma-xiuyuan/mqtt_spy")
from pub import connect, publish

DEV = "AABBCC000001"
AD = "devices/%s/adornment" % DEV
DI = "devices/%s/direct" % DEV
DS = "devices/%s/desired_state" % DEV

CANDS = [
    (AD, json.dumps({"led_glbcfg": 0})),
    (AD, json.dumps({"_led_glbcfg": "0"})),
    (AD, json.dumps({"cmd": "ledbrightness", "data": "0"})),
    (AD, json.dumps({"accesspoint": {"adornment": {"led_glbcfg": 0}}})),
    (AD, json.dumps({"_adornment": {"_led_glbcfg": 0}})),
    (DI, json.dumps({"cmd": "ledbrightness", "data": "0"})),
    (DI, json.dumps({"cmd": "syncledconfig", "data": "0"})),
    (DS, json.dumps({"led_glbcfg": 0})),
    (DS, json.dumps({"desired": {"led_glbcfg": 0}})),
    (AD, "ledbrightness=0"),
    (AD, "led_glbcfg=0"),
    (AD, "0"),
]


def connected():
    try:
        out = subprocess.run(["ss", "-tn"], capture_output=True, text=True, timeout=5).stdout
        return ":8883" in out and "192.168.3.2:" in out
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
s = connect("ledjson")
for i, (topic, payload) in enumerate(CANDS, 1):
    print("【JSON 第 %d 发】%s  主题=%s" % (i, time.strftime("%H:%M:%S"), topic.split("/")[-1]), flush=True)
    print("          %s" % payload, flush=True)
    publish(s, topic, payload, 1)
    time.sleep(12)

print("\n第二轮发完。", flush=True)
s.close()
