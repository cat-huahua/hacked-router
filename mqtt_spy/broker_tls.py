#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MQTT broker：1883 明文 + 8883 TLS。冒充 mqtt.wifi-analytics.singnet.com.sg"""
import socket, struct, threading, time, sys, ssl, os

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "spy.log")
lock = threading.Lock()
subs = {}


def log(*a):
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with lock:
        open(LOG, "a").write(line + "\n")


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


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise ConnectionError("eof")
        buf += c
    return buf


def read_remlen(s):
    mult = 1
    val = 0
    while True:
        b = recv_exact(s, 1)[0]
        val += (b & 0x7F) * mult
        if not (b & 0x80):
            break
        mult *= 128
        if mult > 128 ** 3:
            raise ValueError("bad remlen")
    return val


def match(filt, topic):
    if filt == "#":
        return True
    if filt.endswith("/#"):
        return topic.startswith(filt[:-1])
    if "+" in filt:
        f = filt.split("/")
        t = topic.split("/")
        if len(f) != len(t):
            return False
        return all(a == "+" or a == b for a, b in zip(f, t))
    return filt == topic


def handle(c, addr, via):
    me = {"addr": addr, "cid": None, "subs": set()}
    try:
        while True:
            hdr = recv_exact(c, 1)[0]
            typ = hdr >> 4
            ln = read_remlen(c)
            body = recv_exact(c, ln) if ln else b""

            if typ == 1:  # CONNECT
                i = 2 + struct.unpack("!H", body[0:2])[0]
                level = body[i]
                cflags = body[i + 1]
                i += 3 + 2
                cl = struct.unpack("!H", body[i:i + 2])[0]
                i += 2
                cid = body[i:i + cl].decode("utf-8", "replace")
                i += cl
                user = pwd = None
                if cflags & 0x80:
                    ul = struct.unpack("!H", body[i:i + 2])[0]
                    i += 2
                    user = body[i:i + ul].decode("utf-8", "replace")
                    i += ul
                if cflags & 0x40:
                    pl = struct.unpack("!H", body[i:i + 2])[0]
                    i += 2
                    pwd = body[i:i + pl]
                me["cid"] = cid
                log("*** CONNECT [%s] %s clientid=%r proto=%d user=%r pass=%r clean=%d"
                    % (via, addr[0], cid, level, user, pwd, (cflags >> 1) & 1))
                c.sendall(b"\x20\x02\x00\x00")

            elif typ == 3:  # PUBLISH
                tl = struct.unpack("!H", body[0:2])[0]
                topic = body[2:2 + tl].decode("utf-8", "replace")
                i = 2 + tl
                qos = (hdr >> 1) & 3
                pid = None
                if qos > 0:
                    pid = struct.unpack("!H", body[i:i + 2])[0]
                    i += 2
                payload = body[i:]
                log("*** PUBLISH [%s] %s topic=%r qos=%d retain=%d len=%d payload=%r"
                    % (via, addr[0], topic, qos, hdr & 1, len(payload), payload[:400]))
                if len(payload) > 400:
                    import base64 as _b64
                    log("    full-b64: %s" % _b64.b64encode(payload).decode())
                if qos == 1 and pid is not None:
                    c.sendall(b"\x40\x02" + struct.pack("!H", pid))
                delivered = 0
                for filt, cs in list(subs.items()):
                    if match(filt, topic):
                        for dst in list(cs):
                            if dst is c:
                                continue
                            try:
                                out = topic.encode()
                                dst.sendall(b"\x30" + enc_remlen(2 + len(out) + len(payload))
                                            + struct.pack("!H", len(out)) + out + payload)
                                delivered += 1
                            except Exception as e:
                                log("    !! 转发失败 %s: %s" % (dst.getpeername(), e))
                if delivered:
                    log("    -> 已转发给 %d 个订阅者" % delivered)
                elif not any(match(f, topic) for f in subs):
                    log("    (无匹配订阅者，消息丢弃)")

            elif typ == 8:  # SUBSCRIBE
                pid = struct.unpack("!H", body[0:2])[0]
                i = 2
                codes = []
                while i < len(body):
                    fl = struct.unpack("!H", body[i:i + 2])[0]
                    i += 2
                    filt = body[i:i + fl].decode("utf-8", "replace")
                    i += fl
                    q = body[i]
                    i += 1
                    codes.append(q)
                    me["subs"].add(filt)
                    subs.setdefault(filt, set()).add(c)
                    log("*** SUBSCRIBE [%s] %s topic=%r qos=%d" % (via, addr[0], filt, q))
                c.sendall(b"\x90" + enc_remlen(2 + len(codes))
                          + struct.pack("!H", pid) + bytes(codes))

            elif typ == 10:  # UNSUBSCRIBE
                pid = struct.unpack("!H", body[0:2])[0]
                i = 2
                while i < len(body):
                    fl = struct.unpack("!H", body[i:i + 2])[0]
                    i += 2
                    filt = body[i:i + fl].decode("utf-8", "replace")
                    i += fl
                    log("*** UNSUBSCRIBE [%s] %s topic=%r" % (via, addr[0], filt))
                    subs.get(filt, set()).discard(c)
                    me["subs"].discard(filt)
                c.sendall(b"\xb0\x02" + struct.pack("!H", pid))

            elif typ == 12:  # PINGREQ
                c.sendall(b"\xd0\x00")

            elif typ == 14:  # DISCONNECT
                log("*** DISCONNECT [%s] %s clientid=%r" % (via, addr[0], me["cid"]))
                break

            else:
                log("未知包 [%s] %s type=%d body=%r" % (via, addr[0], typ, body[:80]))
    except Exception as e:
        log("断开 [%s] %s clientid=%r (%s)" % (via, addr[0], me["cid"], type(e).__name__))
    finally:
        for f in list(me["subs"]):
            subs.get(f, set()).discard(c)
        try:
            c.close()
        except Exception:
            pass


def serve(port, ctx=None):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(64)
    via = "TLS" if ctx else "PLAIN"
    log("监听 %d (%s) 就绪" % (port, via))
    while True:
        c, a = s.accept()
        if ctx:
            try:
                c = ctx.wrap_socket(c, server_side=True)
                log(">>> TLS 握手成功 <- %s" % a[0])
            except Exception as e:
                log("TLS 握手失败 <- %s (%s: %s)" % (a[0], type(e).__name__, str(e)[:80]))
                try:
                    c.close()
                except Exception:
                    pass
                continue
        threading.Thread(target=handle, args=(c, a, via), daemon=True).start()


if __name__ == "__main__":
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(os.path.join(HERE, "cert.pem"), os.path.join(HERE, "key.pem"))
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # 兼容老设备：放开所有协议版本与弱算法
    try:
        ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
    except Exception:
        pass
    try:
        ctx.set_ciphers("ALL:@SECLEVEL=0")
    except Exception as e:
        print("set_ciphers:", e, flush=True)
    threading.Thread(target=serve, args=(1883, None), daemon=True).start()
    serve(8883, ctx)
