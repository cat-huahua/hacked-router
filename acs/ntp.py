#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
极简 NTP 服务器 —— 给那几台 mesh 节点对时用

为什么需要：设备的 NTP 服务器是 ntp5/ntp6.singnet.com.sg（Singtel 内网域名），
在 StarHub 线路上够不着，所以它的时钟永远停在 2016-11-01。
DNS 已经把那两个域名劫持到本机，这里再补一个 NTP 服务，时钟就能同步了。

只处理最基本的 NTPv4 客户端请求（模式 3 → 模式 4），够嵌入式设备用。
"""
import socket
import struct
import sys
import time

# NTP 纪元是 1900-01-01，Unix 是 1970-01-01，差 2208988800 秒
NTP_EPOCH = 2208988800


def to_ntp(ts):
    """unix 时间戳 -> NTP 64 位定点数（高 32 位秒，低 32 位小数）"""
    sec = int(ts) + NTP_EPOCH
    frac = int((ts - int(ts)) * (1 << 32))
    return struct.pack("!II", sec & 0xFFFFFFFF, frac & 0xFFFFFFFF)


def handle(data, addr, sock):
    if len(data) < 48:
        return
    li_vn_mode = data[0]
    mode = li_vn_mode & 0x07
    if mode not in (1, 3):          # 只答客户端请求
        return
    vn = (li_vn_mode >> 3) & 0x07 or 4

    now = time.time()
    # 取客户端发来的 transmit timestamp（字节 40-47），原样回填到 originate
    originate = data[40:48]

    resp = bytearray(48)
    resp[0] = (0 << 6) | (vn << 3) | 4      # LI=0 VN=vn Mode=4(server)
    resp[1] = 1                              # stratum 1
    resp[2] = data[2]                        # poll（沿用客户端的）
    resp[3] = 0xEC                           # precision ≈ 2^-20
    resp[4:8] = struct.pack("!I", 0x00010000)      # root delay
    resp[8:12] = struct.pack("!I", 0x00010000)     # root dispersion
    resp[12:16] = b"LOCL"                    # reference id
    resp[16:24] = to_ntp(now - 1)            # reference timestamp
    resp[24:32] = originate                  # originate = 客户端发来的
    resp[32:40] = to_ntp(now)                # receive timestamp
    resp[40:48] = to_ntp(now)                # transmit timestamp
    sock.sendto(bytes(resp), addr)
    return mode


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # ★ 必须绑在别名 IP 上！绑 0.0.0.0 的话，内核会拿主地址 192.168.3.224 当源地址回包，
    #   而设备是往 192.168.3.250 发的 —— 严格的 NTP 客户端会丢弃源地址不符的应答。
    #   （这就是设备 681 次重试、时钟永远停在 2016 的原因）
    sock.bind(("192.168.3.250", 123))
    print("NTP 服务启动，监听 192.168.3.250:123（源地址已修正）", flush=True)
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            mode = handle(data, addr, sock)
            if mode:
                print(f"  {time.strftime('%H:%M:%S')} 回应 {addr[0]} 的对时请求(mode={mode})", flush=True)
        except Exception as e:
            print("  出错:", e, flush=True)


if __name__ == "__main__":
    main()
