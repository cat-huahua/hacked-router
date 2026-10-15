#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐个编号发送 LED 关闭候选格式，间隔 12 秒，方便肉眼归因。"""
import time, sys, subprocess
sys.path.insert(0, "/home/ma-xiuyuan/mqtt_spy")
from pub import connect, publish

DEV = "AABBCC000001"
AD = "devices/%s/adornment" % DEV
DI = "devices/%s/direct" % DEV
DS = "devices/%s/desired_state" % DEV

CANDS = [
    (AD, "/accesspoint?_adornment&_led_glbcfg=0"),
    (AD, "/accesspoint?_adornment&_led_onoff=0"),
    (AD, "/accesspoint?_led_glbcfg=0"),
    (AD, "/accesspoint?_ledbrightness&_data=0"),
    (AD, "/accesspoint?ledbrightness&data=0"),
    (AD, "/accesspoint?cmd=ledbrightness&data=0"),
    (AD, "/accesspoint?_syncledconfig&_led_glbcfg=0"),
    (DI, "/accesspoint?_adornment&_led_glbcfg=0"),
    (DI, "/accesspoint?cmd=ledbrightness&data=0"),
    (DS, "/accesspoint?_adornment&_led_glbcfg=0"),
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
s = connect("ledoff")
for i, (topic, payload) in enumerate(CANDS, 1):
    t = time.strftime("%H:%M:%S")
    print("【第 %d 发】%s  主题=%s" % (i, t, topic.split("/")[-1]), flush=True)
    print("          %s" % payload, flush=True)
    publish(s, topic, payload, 1)
    time.sleep(12)

print("\n发完了。哪一发的效果是灯灭？", flush=True)
s.close()
