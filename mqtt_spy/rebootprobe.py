#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用"重启"当探针：发几个 reboot 变体，看 MQTT 连接会不会断。
   连接一断 = 命令格式对了。避开 factoryreboot（会抹配置）。"""
import time, sys, subprocess
sys.path.insert(0, "/home/ma-xiuyuan/mqtt_spy")
from pub import connect, publish

DEV = "AABBCC000001"
AD = "devices/%s/adornment" % DEV
DI = "devices/%s/direct" % DEV
DS = "devices/%s/desired_state" % DEV

CANDS = [
    (DI, "/accesspoint?_reboot"),
    (DI, "/accesspoint?reboot"),
    (DI, "/accesspoint?cmd=reboot"),
    (AD, "/accesspoint?_reboot"),
    (DS, "/accesspoint?_reboot"),
    (DI, "/accesspoint?_reboot&_device_id=%s" % DEV),
    (DI, "reboot"),
    (DI, "_reboot"),
]


def conns():
    try:
        out = subprocess.run(["ss", "-tn"], capture_output=True, text=True, timeout=5).stdout
        return sum(1 for l in out.splitlines() if ":8883" in l and "192.168.3." in l)
    except Exception:
        return -1


print("起始连接数: %d" % conns(), flush=True)
s = connect("rebootprobe")
for i, (topic, payload) in enumerate(CANDS, 1):
    before = conns()
    print("\n【第 %d 发】%s 主题=%s" % (i, time.strftime("%H:%M:%S"), topic.split("/")[-1]), flush=True)
    print("        %s" % payload, flush=True)
    publish(s, topic, payload, 1)
    time.sleep(14)
    after = conns()
    print("        连接数 %d -> %d %s" % (before, after, "  ★★★ 有变化！" if before != after else ""), flush=True)

print("\n探测结束。设备没重启的话，说明这些格式也不对。", flush=True)
s.close()
