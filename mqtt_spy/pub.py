#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""往间谍 broker 发消息，由 broker 转发给 mesh 设备。

用法:  python3 pub.py <topic> <payload> [qos]
"""
import socket, struct, sys, time, ssl

HOST = "127.0.0.1"
PORT = 1883
DEV = "AABBCC000001"


def enc_remlen(n):
    o = b""
    while True:
        b = n % 128
        n //= 128
        if n > 0:
            b |= 0x80
        o += bytes([b])
        if n == 0:
            break
    return o


def strf(s):
    b = s.encode() if isinstance(s, str) else s
    return struct.pack("!H", len(b)) + b


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise ConnectionError("eof")
        buf += c
    return buf


def connect(cid="pubtool"):
    s = socket.create_connection((HOST, PORT), timeout=8)
    vh = b"\x00\x04MQTT\x04\x02\x00\x3c"
    rem = vh + strf(cid)
    s.sendall(b"\x10" + enc_remlen(len(rem)) + rem)
    ack = recv_exact(s, 4)
    if ack[3] != 0:
        raise RuntimeError("CONNACK 失败 rc=%d" % ack[3])
    return s


def publish(s, topic, payload, qos=0):
    body = strf(topic) + (struct.pack("!H", 1) if qos else b"") + \
           (payload.encode() if isinstance(payload, str) else payload)
    hdr = 0x30 | (qos << 1)
    s.sendall(bytes([hdr]) + enc_remlen(len(body)) + body)
    if qos == 1:
        try:
            s.settimeout(5)
            recv_exact(s, 4)          # PUBACK
        except Exception:
            pass


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "devices/%s/adornment" % DEV
    payload = sys.argv[2] if len(sys.argv) > 2 else "/accesspoint?_adornment"
    qos = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    s = connect()
    print("已连上 broker，发布 topic=%r qos=%d" % (topic, qos))
    print("  payload = %r" % payload)
    publish(s, topic, payload, qos)
    print("  已发出")
    time.sleep(1)
    s.close()
