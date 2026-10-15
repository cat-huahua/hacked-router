#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第四轮：设备所有出站 payload 都是 zlib 压缩的，入站极可能也要求压缩。
   这次用 zlib 压缩后再发。"""
import time, sys, subprocess, zlib
sys.path.insert(0, "/home/ma-xiuyuan/mqtt_spy")
from pub import connect, publish

DEV = "AABBCC000001"
AD = "devices/%s/adornment" % DEV
DI = "devices/%s/direct" % DEV
DS = "devices/%s/desired_state" % DEV

PLAIN = [
    (AD, "/accesspoint?_adornment&_led_glbcfg=1"),
    (AD, "/accesspoint?_adornment&_led_glbcfg=0"),
    (AD, "/accesspoint?_adornment&_led_glbcfg=2"),
    (AD, "/accesspoint?_adornment&_device_id=%s&_led_glbcfg=1" % DEV),
    (AD, "/accesspoint?_adornment&_device_id=%s&_led_glbcfg=0" % DEV),
    (DI, "/accesspoint?_adornment&_led_glbcfg=1"),
    (DS, "/accesspoint?_adornment&_led_glbcfg=1"),
]
CANDS = [(t, zlib.compress(p.encode())) for t, p in PLAIN]


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
s = connect("ledzlib")
for i, ((topic, plain), (_, payload)) in enumerate(zip(PLAIN, CANDS), 1):
    print("【zlib 第 %d 发】%s  主题=%s" % (i, time.strftime("%H:%M:%S"), topic.split("/")[-1]), flush=True)
    print("          明文: %s" % plain, flush=True)
    print("          压缩后 %d 字节: %s" % (len(payload), payload[:24].hex()), flush=True)
    publish(s, topic, payload, 1)
    time.sleep(13)

print("\n第四轮发完。灯有变化吗？", flush=True)
s.close()
