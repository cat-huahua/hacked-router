#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最小 MQTT 3.1.1 broker —— 专门用来冒充 mqtt.wifi-analytics.singnet.com.sg
把那几台 mesh 节点的云端通道接过来，看它们到底在说什么。

只实现必需的部分：CONNECT/CONNACK, SUBSCRIBE/SUBACK, PUBLISH, PINGREQ/PINGRESP, DISCONNECT
"""
import os
import socket, struct, threading, time, sys, os

LOG = os.path.expanduser("~/mqtt_spy/spy.log")
BIND = ("0.0.0.0", 1883)
lock = threading.Lock()
subs = {}          # topic_filter -> set(conn)
conns = {}

def log(*a):
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with lock:
        with open(LOG, "a") as f:
            f.write(line + "\n")

def enc_remlen(n):
    o = b""
    while True:
        b = n % 128; n //= 128
        if n > 0: b |= 0x80
        o += bytes([b])
        if n == 0: break
    return o

def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c: raise ConnectionError("eof")
        buf += c
    return buf

def read_remlen(s):
    mult = 1; val = 0
    while True:
        b = recv_exact(s, 1)[0]
        val += (b & 0x7f) * mult
        if not (b & 0x80): break
        mult *= 128
        if mult > 128**3: raise ValueError("bad remlen")
    return val

def match(filt, topic):
    if filt == "#": return True
    if filt.endswith("/#"): return topic.startswith(filt[:-1])
    if "+" in filt:
        f = filt.split("/"); t = topic.split("/")
        if len(f) != len(t): return False
        return all(a == "+" or a == b for a, b in zip(f, t))
    return filt == topic

def handle(c, addr):
    me = {"addr": addr, "cid": None, "subs": set()}
    try:
        while True:
            hdr = recv_exact(c, 1)[0]
            typ = hdr >> 4; flags = hdr & 0x0F
            ln = read_remlen(c)
            body = recv_exact(c, ln) if ln else b""

            if typ == 1:                                  # CONNECT
                i = 0
                pl = struct.unpack("!H", body[0:2])[0]; i = 2 + pl
                level = body[i]; cflags = body[i+1]; i += 3
                i += 2                                     # keepalive
                cl = struct.unpack("!H", body[i:i+2])[0]; i += 2
                cid = body[i:i+cl].decode("utf-8","replace"); i += cl
                user = pwd = None
                if cflags & 0x80:
                    ul = struct.unpack("!H", body[i:i+2])[0]; i += 2
                    user = body[i:i+ul].decode("utf-8","replace"); i += ul
                if cflags & 0x40:
                    pl2 = struct.unpack("!H", body[i:i+2])[0]; i += 2
                    pwd = body[i:i+pl2]
                me["cid"] = cid
                log("CONNECT  %s  clientid=%r proto=%d user=%r pass=%r clean=%d" % (
                    addr[0], cid, level, user, pwd, (cflags >> 1) & 1))
                c.sendall(b"\x20\x02\x00\x00")             # CONNACK 接受
                conns[cid] = me

            elif typ == 3:                                # PUBLISH
                tl = struct.unpack("!H", body[0:2])[0]
                topic = body[2:2+tl].decode("utf-8","replace")
                i = 2 + tl
                qos = (hdr >> 1) & 3
                pid = None
                if qos > 0:
                    pid = struct.unpack("!H", body[i:i+2])[0]; i += 2
                payload = body[i:]
                log("PUBLISH  %s  topic=%r qos=%d retain=%d pid=%s payload=%r" % (
                    addr[0], topic, qos, hdr & 1, pid, payload[:400]))
                if qos == 1 and pid is not None:
                    c.sendall(b"\x40\x02" + struct.pack("!H", pid))   # PUBACK
                # 转发给订阅者
                for filt, cs in list(subs.items()):
                    if match(filt, topic):
                        for dst in list(cs):
                            if dst is c: continue
                            try:
                                out = topic.encode()
                                pkt = b"\x30" + enc_remlen(2+len(out)+len(payload)) + \
                                      struct.pack("!H", len(out)) + out + payload
                                dst.sendall(pkt)
                            except Exception: pass

            elif typ == 8:                                # SUBSCRIBE
                pid = struct.unpack("!H", body[0:2])[0]
                i = 2; codes = []
                while i < len(body):
                    fl = struct.unpack("!H", body[i:i+2])[0]; i += 2
                    filt = body[i:i+fl].decode("utf-8","replace"); i += fl
                    q = body[i]; i += 1
                    codes.append(q)
                    me["subs"].add(filt)
                    subs.setdefault(filt, set()).add(c)
                    log("SUBSCRIBE %s  topic=%r qos=%d" % (addr[0], filt, q))
                c.sendall(b"\x90" + enc_remlen(2+len(codes)) + struct.pack("!H", pid) + bytes(codes))

            elif typ == 10:                               # UNSUBSCRIBE
                pid = struct.unpack("!H", body[0:2])[0]
                i = 2
                while i < len(body):
                    fl = struct.unpack("!H", body[i:i+2])[0]; i += 2
                    filt = body[i:i+fl].decode("utf-8","replace"); i += fl
                    log("UNSUBSCRIBE %s topic=%r" % (addr[0], filt))
                    subs.get(filt, set()).discard(c)
                    me["subs"].discard(filt)
                c.sendall(b"\xb0\x02" + struct.pack("!H", pid))

            elif typ == 12:                               # PINGREQ
                c.sendall(b"\xd0\x00")

            elif typ == 14:                               # DISCONNECT
                log("DISCONNECT %s clientid=%r" % (addr[0], me["cid"]))
                break
            else:
                log("未知包 type=%d len=%d body=%r" % (typ, ln, body[:80]))
    except Exception as e:
        log("断开 %s clientid=%r (%s)" % (addr[0], me["cid"], type(e).__name__))
    finally:
        for filt in list(me["subs"]):
            subs.get(filt, set()).discard(c)
        try: c.close()
        except Exception: pass

def main():
    log("=" * 70)
    log("MQTT 间谍 broker 启动，监听 %s:%d" % BIND)
    log("冒充域名: mqtt.wifi-analytics.singnet.com.sg")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(BIND); s.listen(64)
    while True:
        try:
            c, a = s.accept()
            threading.Thread(target=handle, args=(c, a), daemon=True).start()
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    main()
