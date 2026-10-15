#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HUAWEI WiFi Q2S (WS5281-10) HiLink API 客户端
用途：批量整理 静态 IP 地址绑定 列表 + 收窄 DHCP 动态池

用法：
    python3 router.py check          # 只读：打印当前 DHCP 设置 + 绑定表 + 在线设备
    python3 router.py plan           # 只读：对比目标规划，列出要改什么
    python3 router.py apply          # 执行改动（会二次确认，需输入 yes）
    python3 router.py apply --pool   # 顺带把 DHCP 池收窄到 3.200-3.254

密码通过 getpass 输入，不进 argv、不进 shell history。
"""
import argparse
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import time

import requests

DEFAULT_HOST = os.environ.get("HW_HOST", "http://192.168.3.1")

# ---------------------------------------------------------------------------
# 目标规划：MAC -> 期望 IP
# 只有 comment 里写了「改」的才和现状不同；其余是幂等的锚点，
# 保留在表里是为了 plan 能发现「谁被手动改歪了」。
# ---------------------------------------------------------------------------
TARGET = {
    # ── 下面是【示例表】，请换成你自己家的 MAC ──
    # 只有 comment 里写「改」的才和现状不同；其余是幂等的锚点，
    # 保留在表里是为了 plan 能发现「谁被手动改歪了」。
    "AA:BB:CC:00:00:01": ("192.168.3.2",   "Mesh 主节点（不动）"),
    "AA:BB:CC:11:00:01": ("192.168.3.3",   "AP / 交换机（不动）"),
    "AA:BB:CC:11:00:02": ("192.168.3.10",  "子路由 1（不动）"),
    "AA:BB:CC:11:00:03": ("192.168.3.11",  "子路由 2（不动）"),
    "AA:BB:CC:11:00:04": ("192.168.3.12",  "改：原在动态池内，子路由 3"),
    "AA:BB:CC:00:00:02": ("192.168.3.20",  "Mesh 卫星 1（不动）"),
    "AA:BB:CC:00:00:03": ("192.168.3.21",  "改：原 3.49，Mesh 卫星 2"),
    "AA:BB:CC:00:00:04": ("192.168.3.22",  "改：原 3.50，Mesh 卫星 3"),
    "AA:BB:CC:22:00:01": ("192.168.3.30",  "笔记本 A（不动）"),
    "AA:BB:CC:22:00:02": ("192.168.3.31",  "改：原在动态池内，笔记本 B"),
    "AA:BB:CC:22:00:03": ("192.168.3.50",  "智能设备 1（不动）"),
    "AA:BB:CC:22:00:04": ("192.168.3.51",  "智能设备 2（不动）"),
    "AA:BB:CC:33:00:01": ("192.168.3.60",  "打印机 A（不动）"),
    "AA:BB:CC:33:00:02": ("192.168.3.62",  "打印机 B（不动）"),
    "AA:BB:CC:33:00:03": ("192.168.3.70",  "改：原 3.86，打印机 C"),
    "AA:BB:CC:33:00:04": ("192.168.3.71",  "改：原 3.109，打印机 D"),
    "AA:BB:CC:44:00:01": ("192.168.3.150", "NAS / iKVM（不动）"),
    "AA:BB:CC:44:00:02": ("192.168.3.155", "NAS 主（不动，改了会断 CIFS mount）"),
    "AA:BB:CC:44:00:03": ("192.168.3.159", "NAS 副（不动）"),
    "AA:BB:CC:44:00:04": ("192.168.3.160", "虚拟机 / 服务（不动）"),
}

POOL_START = "192.168.3.200"
POOL_END = "192.168.3.254"


def norm_mac(m):
    return (m or "").replace("-", ":").upper()


# ---------------------------------------------------------------------------
# SCRAM-SHA256 登录（照抄 store.js 里 login action 的算法）
# ---------------------------------------------------------------------------
class Router:
    def __init__(self, host=DEFAULT_HOST):
        self.base = host.rstrip("/") + "/api/"
        self.host = host.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({
            "_ResponseFormat": "JSON",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": self.host + "/html/index.html",
            "Origin": self.host,
        })
        self.csrf = {}
        self.level = None

    def seed_csrf(self):
        """未登录时唯一的开放接口；它顺带下发 SessionID_R3 cookie 和第一组 csrf。"""
        d = self.get("system/deviceinfo")
        if d.get("csrf_param"):
            self.csrf = {"csrf_param": d["csrf_param"], "csrf_token": d["csrf_token"]}
        return d

    # -- 底层 ---------------------------------------------------------------
    def get(self, path, params=None):
        r = self.s.get(self.base + path, params=params, timeout=15)
        r.raise_for_status()
        j = self._json(r)
        self._absorb_csrf(j)      # GET 的响应同样会轮换 csrf，不接就会过期
        return j

    def _absorb_csrf(self, j):
        if isinstance(j, dict) and j.get("csrf_param"):
            self.csrf = {"csrf_param": j["csrf_param"], "csrf_token": j["csrf_token"]}

    def post(self, path, body, with_csrf=True):
        body = dict(body)
        if with_csrf:
            body.setdefault("csrf", self.csrf)
        r = self.s.post(self.base + path, json=body, timeout=25,
                        headers={"Content-Type": "application/json; charset=utf-8"})
        r.raise_for_status()
        j = self._json(r)
        if isinstance(j, dict) and j.get("csrf_param"):
            self.csrf = {"csrf_param": j["csrf_param"], "csrf_token": j["csrf_token"]}
        return j

    @staticmethod
    def _json(r):
        try:
            return r.json()
        except ValueError:
            return {"_raw": r.text, "_status": r.status_code}

    # -- 登录 ---------------------------------------------------------------
    def login(self, username="admin", password=None):
        if password is None:
            password = getpass.getpass("路由器管理密码 (输入不回显): ")

        # csrf 是单次令牌，偶发 Menu.csrf_err。这一步还没碰到密码，
        # 失败不消耗 maxfailtimes，所以放心重试。JS 端同样是重试 5 次。
        res = None
        for _ in range(6):
            if not self.csrf:
                self.seed_csrf()
            first_nonce = secrets.token_hex(32)
            res = self.post("system/user_login_nonce",
                            {"data": {"username": username, "firstnonce": first_nonce}})
            if res.get("err") == 0:
                break
            self.csrf = {}          # 扔掉旧令牌重新种
            time.sleep(0.5)
        if not res or res.get("err") != 0:
            raise SystemExit("① nonce 阶段失败(已重试 6 次): %s"
                             % json.dumps(res, ensure_ascii=False))

        salt = bytes.fromhex(res["salt"])
        iters = int(res["iterations"])
        server_nonce = res["servernonce"]

        # 华为的 authMsg：firstNonce,servernonce,servernonce
        auth_msg = "%s,%s,%s" % (first_nonce, server_nonce, server_nonce)

        # ⚠️ 华为这份 SCRAMJS v1.0.1 的 HMAC 参数顺序是反的（不符合 RFC 5802）：
        #    它把 CryptoJS 的 HmacSHA256(message, key) 当成 (key, message) 用了。
        #    所以下面三条 HMAC 的 key/msg 位置和教科书相反 —— 但这才是路由器认的算法。
        #    已用 Node 跑路由器自带的 cat_enc.js 逐字段比对通过（见 selftest()）。
        salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters, 32)
        client_key = hmac.new(b"Client Key", salted, hashlib.sha256).digest()
        stored_key = hashlib.sha256(client_key).digest()
        client_sig = hmac.new(auth_msg.encode("utf-8"), stored_key, hashlib.sha256).digest()
        client_proof = bytes(a ^ b for a, b in zip(client_key, client_sig))

        res2 = self.post("system/user_login_proof",
                         {"data": {"clientproof": client_proof.hex(),
                                   "finalnonce": server_nonce}})
        if res2.get("err") != 0:
            raise SystemExit("② 登录失败（密码不对？）: %s"
                             % json.dumps(res2, ensure_ascii=False))

        # 协议自带的双向校验：用 serverKey 重算，和路由器给的 serversignature 对一下。
        # 对得上 => 我的 SCRAM 实现和路由器完全一致；对不上 => 后面所有请求都不能信。
        server_key = hmac.new(b"Server Key", salted, hashlib.sha256).digest()
        expect = hmac.new(auth_msg.encode("utf-8"), server_key, hashlib.sha256).digest().hex()
        if res2.get("serversignature") != expect:
            raise SystemExit("③ 服务端签名不匹配，SCRAM 实现有偏差，已中止")
        print("  ✓ SCRAM 双向校验通过 (level=%s)" % res2.get("level"))
        self.level = res2.get("level")
        return res2

    # -- 业务接口 -----------------------------------------------------------
    def lan_server(self):
        return self.get("ntwk/lan_server")

    def bindings(self):
        r = self.get("ntwk/lan_ipaddressreserve")
        if isinstance(r, list):          # 这个固件直接返回裸数组
            return r
        return r.get("data") or r.get("IpAddrReserve") or r

    def hosts(self):
        r = self.get("system/HostInfo")
        return r.get("Hosts") or r.get("data") or r


# ---------------------------------------------------------------------------
def dump(o):
    return json.dumps(o, ensure_ascii=False, indent=2, sort_keys=True)


def cmd_check(rt):
    print("\n=== DHCP 服务器 (/api/ntwk/lan_server) ===")
    srv = rt.lan_server()
    print(dump(srv))
    print("\n=== 静态 IP 绑定表 (/api/ntwk/lan_ipaddressreserve) ===")
    b = rt.bindings()
    if isinstance(b, list):
        for i, it in enumerate(b, 1):
            print("  %2d  %-18s %-16s enable=%s"
                  % (i, norm_mac(it.get("Chaddr")), it.get("Yiaddr"), it.get("Enable")))
    else:
        print(dump(b))


def cmd_plan(rt):
    b = rt.bindings()
    if not isinstance(b, list):
        print("绑定表格式意外，原始返回："); print(dump(b)); return
    by_mac = {norm_mac(i.get("Chaddr")): i for i in b}

    print("\n%-20s %-14s %-14s %s" % ("MAC", "现在", "目标", "说明"))
    print("-" * 78)
    todo, missing, same = [], [], 0
    for mac, (want, note) in TARGET.items():
        cur = by_mac.get(mac)
        if cur is None:
            missing.append((mac, want, note)); continue
        have = cur.get("Yiaddr")
        if have == want:
            same += 1
        else:
            todo.append((mac, have, want, note))
            print("%-20s %-14s %-14s %s" % (mac, have, want, note))
    print("-" * 78)
    print("要改 %d 条，已正确 %d 条，表中缺失 %d 条" % (len(todo), same, len(missing)))
    for mac, want, note in missing:
        print("  ! 绑定表里没有 %s（目标 %s，%s）" % (mac, want, note))

    srv = rt.lan_server()
    mn, mx = srv.get("MinIP"), srv.get("MaxIP")
    print("\n当前 DHCP 动态池: %s - %s" % (mn, mx))
    print("建议动态池:       %s - %s" % (POOL_START, POOL_END))
    if mn == POOL_START and mx == POOL_END:
        print("  ✓ 池已经收窄到位")
    else:
        print("  → 用 `apply --pool` 收窄")
    print()


def cmd_apply(rt, do_pool=False, assume_yes=False):
    srv = rt.lan_server()
    b = rt.bindings()
    if not isinstance(b, list):
        raise SystemExit("绑定表格式意外，已中止。原始：%s" % dump(b))
    by_mac = {norm_mac(i.get("Chaddr")): i for i in b}

    todo = []
    for mac, (want, note) in TARGET.items():
        cur = by_mac.get(mac)
        if cur is not None and cur.get("Yiaddr") != want:
            todo.append((mac, cur.get("Yiaddr"), want, note, cur))

    print("\n将执行 %d 条改动：" % len(todo))
    for mac, have, want, note, _ in todo:
        print("  %-20s %-14s -> %-14s  %s" % (mac, have, want, note))
    if do_pool:
        print("  池: %s-%s -> %s-%s" % (srv.get("MinIP"), srv.get("MaxIP"),
                                        POOL_START, POOL_END))
    if not todo and not do_pool:
        print("没有要改的。"); return

    if not assume_yes:
        if input("\n确认执行？输入 yes 继续: ").strip() != "yes":
            print("已取消。"); return

    # 1) 先收窄池（把动态地址让出来），再改绑定
    if do_pool:
        new = dict(srv)
        new["MinIP"], new["MaxIP"] = POOL_START, POOL_END
        r = rt.post("ntwk/lan_server", {"data": new})
        ok = r.get("errcode", r.get("err")) in (0, None) and not r.get("error")
        print("池 -> %s-%s : %s" % (POOL_START, POOL_END, "OK" if ok else dump(r)))

    # 2) 逐条改。
    #    ID 非空 => action "update"，一次原子调用原地换 IP；
    #    不用 delete+add（两步之间失败会丢掉绑定，见 lan.js 的 save 分支）。
    for mac, have, want, note, item in todo:
        body = {"Chaddr": mac, "Yiaddr": want, "Enable": True, "ID": item.get("ID", "")}
        action = "update" if item.get("ID") else "create"
        r = rt.post("ntwk/lan_ipaddressreserve", {"data": body, "action": action})
        code = r.get("errcode", r.get("err"))
        ok = code in (0, None)
        print("  %-6s %-18s %-14s -> %-14s %s"
              % (action, mac, have, want, "OK" if ok else dump(r)))
        if not ok:
            print("     ! 失败，继续下一条")

    print("\n完成。被改的设备请断电重启一次（尤其 Mesh 节点）。")


# 路由器自带 cat_enc.js（SCRAMJS v1.0.1）在 Node 里跑出来的标准答案。
# 任何一次改动之后都该跑 `python3 router.py selftest` 确认为止。
VECTORS = {
    "saltedPassword":  "f44afc9bd477686ffffde1677313612cea7038b299391937733a4af0347dd135",
    "clientKey":       "ff810c6e2caf1d6e0eb035884b1415147eb614fa77286182e21a32247db2544d",
    "storedKey":       "dada18d0c90c8397979dd2819ea877627d40e56f75d1dbc8d637628417a82bd5",
    "clientSignature": "e49a78686a29d53480e7ed07f606b3a56b94b3638ba949f4cba32360b9a73b81",
    "clientProof":     "1b1b74064686c85a8e57d88fbd12a6b11522a799fc81287629b91144c4156fcc",
    "serverProof":     "b2e244dcc9aa5a9e2e551ea69b9c4c5b539d696161d9da427af91d07e494d008",
}


def scram_chain(password, salt, iters, auth_msg):
    """返回 SCRAM 中间量，用于登录和自检共用一份实现。"""
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters, 32)
    client_key = hmac.new(b"Client Key", salted, hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    client_sig = hmac.new(auth_msg.encode("utf-8"), stored_key, hashlib.sha256).digest()
    server_key = hmac.new(b"Server Key", salted, hashlib.sha256).digest()
    server_proof = hmac.new(auth_msg.encode("utf-8"), server_key, hashlib.sha256).digest()
    return {
        "saltedPassword": salted.hex(),
        "clientKey": client_key.hex(),
        "storedKey": stored_key.hex(),
        "clientSignature": client_sig.hex(),
        "clientProof": bytes(a ^ b for a, b in zip(client_key, client_sig)).hex(),
        "serverProof": server_proof.hex(),
    }


def selftest():
    salt = bytes.fromhex("0e2b88598094333bc45ff5c57e7ef4a577f6e4724405d61cc7a72bbed2f34d43")
    first = "a" * 64
    server = first + "b" * 32
    got = scram_chain("TestPw123", salt, 100, "%s,%s,%s" % (first, server, server))
    bad = [k for k in VECTORS if got[k] != VECTORS[k]]
    for k in VECTORS:
        print("  %s %-16s %s" % ("✓" if got[k] == VECTORS[k] else "✗", k, got[k]))
    if bad:
        raise SystemExit("\n✗ SCRAM 自检失败: %s —— 先别碰路由器" % ", ".join(bad))
    print("\n✓ 与路由器自带 SCRAMJS 完全一致")


def main():
    ap = argparse.ArgumentParser(description="HUAWEI Q2S 静态 IP 绑定批量整理")
    ap.add_argument("cmd", choices=["selftest", "check", "plan", "apply"])
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--user", default="admin")
    ap.add_argument("--pool", action="store_true", help="apply 时同时收窄 DHCP 池")
    ap.add_argument("--yes", action="store_true", help="跳过确认（配合 apply）")
    a = ap.parse_args()

    if a.cmd == "selftest":
        selftest()
        return

    rt = Router(a.host)
    print("登录 %s ..." % a.host)
    rt.login(a.user)

    {"check": cmd_check,
     "plan": lambda r: cmd_plan(r),
     "apply": lambda r: cmd_apply(r, a.pool, a.yes)}[a.cmd](rt)


if __name__ == "__main__":
    main()
