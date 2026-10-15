#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 Singtel mesh 的 Wi-Fi 信道钉死：2.4G -> 11，5G -> 40

为什么要它：断电重插有时会把无线设置打回默认（信道变回 Auto 之类）。

机制（从 ssid.htm 的 save 逆出）：
    POST /cgi-bin/toplogy.cgi
      httoken = <token>
      cmd     = syncwificonfig
      data    = 17 个字段用 "?$[+" 拼起来，顺序固定：
        1  24g SSID          9  wps 开关
        2  5g  SSID         10  ★ channel_24ghz
        3  2.4G 广播        11  ★ channel_5ghz
        4  5G 广播          12  2.4G 频宽
        5  2.4G 加密        13  2.4G coexistence
        6  5G 加密          14  ldpc
        7  2.4G 密码        15  5G 频宽
        8  5G 密码          16  5G coexistence
                            17  vht
    成功返回 "ok_wifi"

⚠️ 这个 payload 里带 SSID 和明文密码！所以脚本必须先把当前值全读出来原样回填，
   只动第 10/11 两个字段。写错一个字段可能把 Wi-Fi 名或密码搞掉。

用法：
    python3 setch.py            # 只读，显示当前信道
    python3 setch.py --dry-run  # 打印将要发送的 payload，不发送
    python3 setch.py --apply    # 真写
"""
import argparse
import re
import sys
import time

from sg import Mesh

CH24 = "11"
CH5 = "40"


def read_cfg(m):
    """把 cgi_wifi + cgi_wireless_wps 拉成一个大字典"""
    cfg = {}
    for cgi in ("wifi", "wireless_wps", "status"):
        for n, v in re.findall(r'addCfg\("([^"]+)",\s*"[0-9]+",\s*"([^"]*)"', m.cgi(cgi).text):
            cfg[n] = v
    return cfg


def build_payload(cfg, ch24, ch5):
    """按 ssid.htm 里的字段顺序拼 17 段"""
    wps_val = cfg.get("wps_enable", "0")
    wps_index = "1" if wps_val == "1" else "0"   # select 的 option 值是 ['0','1']
    fields = [
        cfg.get("24gname0", ""),            # 1  2.4G SSID
        cfg.get("5gname0", ""),             # 2  5G SSID
        cfg.get("24gbcast0", "0"),          # 3
        cfg.get("5gbcast0", "0"),           # 4
        cfg.get("24gsecurity_mode0", "WPA2PSK"),   # 5
        cfg.get("5gsecurity_mode0", "WPA2PSK"),    # 6
        cfg.get("24gwpapsk0", ""),          # 7  密码
        cfg.get("5gwpapsk0", ""),           # 8  密码
        wps_index,                          # 9
        str(ch24),                          # 10 ★
        str(ch5),                           # 11 ★
        cfg.get("24gbandwidth", "0"),       # 12
        cfg.get("24gcoexistence", "0"),     # 13
        cfg.get("ldpc_24g", "0"),           # 14
        cfg.get("5gbandwidth", "0"),        # 15
        cfg.get("5gcoexistence", "0"),      # 16
        cfg.get("5gvhtBW", "0"),            # 17
    ]
    return "?$[+".join(fields), fields


def show(cfg):
    print("当前无线设置（主 SSID）：")
    print(f"  2.4G SSID    : {cfg.get('24gname0')}")
    print(f"  5G   SSID    : {cfg.get('5gname0')}")
    print(f"  2.4G 加密    : {cfg.get('24gsecurity_mode0')}   密码: {cfg.get('24gwpapsk0')}")
    print(f"  5G   加密    : {cfg.get('5gsecurity_mode0')}   密码: {cfg.get('5gwpapsk0')}")
    print(f"  2.4G 频宽    : {cfg.get('24gbandwidth')}   5G 频宽: {cfg.get('5gbandwidth')}")
    print(f"  ★ 2.4G 信道 : {cfg.get('channel_24ghz')}")
    print(f"  ★ 5G   信道 : {cfg.get('channel_5ghz')}")
    ok24 = cfg.get("channel_24ghz") == CH24
    ok5 = cfg.get("channel_5ghz") == CH5
    print(f"\n  目标 {CH24}/{CH5}  ->  {'✅ 已经是了' if ok24 and ok5 else '⚠ 需要修正'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写入")
    ap.add_argument("--dry-run", action="store_true", help="只打印 payload")
    ap.add_argument("--ch24", default=CH24)
    ap.add_argument("--ch5", default=CH5)
    ap.add_argument("--host", default="192.168.3.2")
    a = ap.parse_args()

    m = Mesh(a.host)
    m.login()
    cfg = read_cfg(m)
    show(cfg)

    payload, fields = build_payload(cfg, a.ch24, a.ch5)
    print(f"\n  待写入信道：2.4G={a.ch24}  5G={a.ch5}")

    if a.dry_run or not a.apply:
        print("\npayload 各段：")
        labels = ["2.4G SSID", "5G SSID", "2.4G bcast", "5G bcast", "2.4G sec", "5G sec",
                  "2.4G psk", "5G psk", "wps", "★2.4G ch", "★5G ch", "24g bw", "24g coex",
                  "ldpc", "5g bw", "5g coex", "5g vht"]
        for lb, v in zip(labels, fields):
            print(f"    {lb:12} = {v!r}")
        if not a.apply:
            print("\n（只读模式。加 --apply 才会真的写）")
        return

    tok = m._token()
    r = m.s.post(m.base + "/cgi-bin/toplogy.cgi",
                 data={"httoken": tok, "cmd": "syncwificonfig", "data": payload},
                 timeout=20, allow_redirects=False)
    print(f"\n写入返回: {r.status_code} {r.text.strip()!r}")
    if r.text.strip() != "ok_wifi":
        print("⚠ 不是 ok_wifi，可能字段对不上，检查上面 payload")
        return
    print("等 mesh 同步（会短暂断线）...")
    time.sleep(25)
    for _ in range(10):
        try:
            cfg2 = read_cfg(m)
            print(f"  回读：2.4G={cfg2.get('channel_24ghz')}  5G={cfg2.get('channel_5ghz')}  "
                  f"SSID={cfg2.get('24gname0')}  密码={cfg2.get('24gwpapsk0')}")
            if cfg2.get("channel_24ghz") == a.ch24 and cfg2.get("channel_5ghz") == a.ch5:
                print("  ✅ 信道已钉死")
            break
        except Exception as e:
            print(f"  控制器还没回来（{str(e)[:40]}），再等 10 秒")
            time.sleep(10)


if __name__ == "__main__":
    main()
