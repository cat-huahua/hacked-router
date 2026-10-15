#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华为路由器的请求体加密（jsbn RSA-OAEP）

照抄 util.js 里的 enc()：
    var enc = function(encstring, rsakey) {
        rsa.setPublic(rsakey[0], rsakey[1]);       // N, E 都是 hex
        var arr = base64_encode(encstring);        // 先 base64
        var num = arr.length / 214;
        for (i = 0; i < num; i++) {
            var encdata = arr.substr(i * 214, 214);   // 每 214 个 base64 字符一块
            var res = rsa.encryptOAEP(encdata);       // ← 加密的是「base64 字符」本身
            if (res.length != rsan.length) { i--; continue; }
            restotal += res;                          // 拼 hex
        }
        return restotal;
    }

关键点：
  · 加密的**不是明文密码**，是它的 **base64 编码**（当字符串处理）
  · 2048 位密钥 + SHA-1 的 OAEP 上限正好是 214 字节 —— 所以 214 是精心选的
  · E 是 010001（65537）
"""
import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

CHUNK = 214


def make_pubkey(n_hex, e_hex="010001"):
    n = int(n_hex, 16)
    e = int(e_hex, 16)
    return rsa.RSAPublicNumbers(e, n).public_key()


def hw_enc(pub, s):
    """复刻华为的 enc()：返回 hex 字符串"""
    b64 = base64.b64encode(s.encode("utf-8")).decode("ascii")
    out = ""
    i = 0
    while i < len(b64):
        piece = b64[i:i + CHUNK]
        i += CHUNK
        ct = pub.encrypt(
            piece.encode("ascii"),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
        )
        out += ct.hex()
    return out


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, "/home/ma-xiuyuan/hw_q2s")
    import router as R

    rt = R.Router()
    rt.login("admin", "WIFI_PASSWORD_HERE")
    k = rt.get("system/encpubkey")
    pub = make_pubkey(k["EncpubkeyN"], k["EncpubkeyE"])
    print("N 位数:", len(k["EncpubkeyN"]), " E:", k["EncpubkeyE"])
    ct = hw_enc(pub, "WIFI_PASSWORD_HERE")
    print("加密结果长度:", len(ct), "hex 字符 (512 = 2048 位 ✓)" if len(ct) == 512 else "⚠ 长度不对")
    print("前 64 字符:", ct[:64])
    print("base64 长度检查: base64('WIFI_PASSWORD_HERE') =", base64.b64encode(b"WIFI_PASSWORD_HERE").decode())
