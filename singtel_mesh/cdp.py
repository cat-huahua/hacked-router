#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最小 CDP 客户端（不依赖任何 websocket 库，纯 socket 手写 WS 帧）。

为什么要它：Singtel 那台的 /cgi-bin/*.exe 后端对非浏览器客户端**一律重置连接**
（curl、python requests 都试过，GET/POST、各种请求头都一样）。
唯一能过的是真浏览器。所以在页面上下文里跑 fetch() —— 那样请求带着
浏览器的 TLS 指纹，服务器才认。

用法（配合 headless chrome --remote-debugging-port=9222）：
    python3 cdp.py "https://192.168.3.2/login.htm" "location.href"
"""
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request


class WS:
    def __init__(self, url):
        # ws://127.0.0.1:9222/devtools/page/XXX
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.s = socket.create_connection((host, int(port)), 10)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n") % (path, hostport, key)
        self.s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        if b"101" not in buf.split(b"\r\n")[0]:
            raise RuntimeError("WS 握手失败: %r" % buf[:200])
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self._id = 0

    def _recv_exact(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise RuntimeError("连接关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, obj):
        payload = json.dumps(obj).encode()
        hdr = b"\x81"                      # FIN + text
        n = len(payload)
        if n < 126:
            hdr += struct.pack("!B", n | 0x80)
        elif n < 65536:
            hdr += struct.pack("!BH", 126 | 0x80, n)
        else:
            hdr += struct.pack("!BQ", 127 | 0x80, n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.s.sendall(hdr + mask + masked)

    def recv(self):
        while True:
            b0, b1 = self._recv_exact(2)
            opcode = b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            data = self._recv_exact(length)
            if opcode == 0x1:
                return json.loads(data.decode())
            if opcode == 0x8:
                raise RuntimeError("服务端关闭 WS")
            # 其它帧（ping/pong/binary）忽略

    def call(self, method, params=None, timeout=30):
        self._id += 1
        mid = self._id
        self.send({"id": mid, "method": method, "params": params or {}})
        t0 = time.time()
        while time.time() - t0 < timeout:
            msg = self.recv()
            if msg.get("id") == mid:
                return msg
        raise TimeoutError(method)


def page_ws(port=9222):
    """拿到一个 type=page 的目标的 ws 地址；没有就新建一个标签页"""
    data = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json" % port, timeout=5).read())
    for t in data:
        if t.get("type") == "page":
            return t["webSocketDebuggerUrl"]
    r = urllib.request.urlopen("http://127.0.0.1:%d/json/new?about:blank" % port, timeout=5)
    return json.loads(r.read())["webSocketDebuggerUrl"]


def evaluate(ws, expr, await_promise=True, timeout=40):
    r = ws.call("Runtime.evaluate", {
        "expression": expr,
        "awaitPromise": await_promise,
        "returnByValue": True,
        "timeout": timeout * 1000,
    }, timeout=timeout + 5)
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return {"error": str(res["exceptionDetails"])[:500]}
    return res.get("result", {}).get("value")


def goto(ws, url, settle=2.0):
    ws.call("Page.navigate", {"url": url})
    time.sleep(settle)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "about:blank"
    expr = sys.argv[2] if len(sys.argv) > 2 else "document.title"
    ws = WS(page_ws())
    ws.call("Page.enable")
    ws.call("Runtime.enable")
    goto(ws, url)
    print(json.dumps(evaluate(ws, expr), ensure_ascii=False, indent=2))
