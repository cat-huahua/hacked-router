#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cfgpack —— Arcadyan / Singtel 路由器的【配置恢复包】工具

解决四个场景（都不需要 root，只要拿到对应的东西）：

  ① 有解包后的 rootfs     → `rootfs`：列出配置包、口令文件、证书、服务凭据
  ② 有 .glbcfg            → `glbcfg`：按模块统计字段，导出所有凭据类字段
  ③ 有官方的 Settings.CFG → `decrypt`：离线解密 web 备份（固定密钥，见下）
  ④ 有整片 SPI flash dump → `carve`：从裸镜像里把配置 tar 包捞出来

★ 关键发现（2026-10-17，从 httpd 反汇编得到）
  web 界面「备份」下载的 Settings.CFG 其实是一条 shell 命令拼出来的：

      tar czf /tmp/.config.tgz -C /tmp/.config/ .
      openssl enc -aes-256-cbc -salt -a -in /tmp/.config.tgz -k xf8V3zOa

  也就是说 —— **加密口令是固件里写死的，全机型通用**，不需要设备就能解。
  算法取自配置项 ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType（默认 aes-256-cbc）。

  ★ 坑：路由器上是 OpenSSL 1.0.1t，`-k` 的默认 KDF 是 **MD5**；
    现代 OpenSSL 3.x 默认改成了 SHA-256。所以必须显式 `-md md5`，
    否则同样的口令会解出乱码。

用法:
    python3 cfgpack.py rootfs  <rootfs目录>
    python3 cfgpack.py glbcfg  <.glbcfg> [-o 字段.tsv]
    python3 cfgpack.py decrypt <Settings.CFG> [-o 输出目录]
    python3 cfgpack.py pack    <配置目录> [-o Settings.CFG]
    python3 cfgpack.py carve   <flash.bin> [-o 输出目录]
"""
import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zlib

WEB_CIPHER = "aes-256-cbc"      # ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType 的出厂值
WEB_KEY = "xf8V3zOa"            # httpd 里写死的 -k 参数
WEB_DIGEST = "md5"              # OpenSSL 1.0.1t 的 enc 默认摘要

# ★ 只挑真正可能存凭据的字段。
#   早先写成 passw|pwd|...|auth|key 太宽，一下子命中 763 个（把 _Enable、
#   _AuthAlgo 全算进来了），反而看不见真正有值的那些。
CRED_RE = re.compile(
    r"(?i)(passw|_pwd\b|\bpwd\b|psk|secret|passphrase|token|credential|"
    r"username|_account|wep_key|wpa_key|_pin\b)")


# ───────────────────────── ② glbcfg ─────────────────────────

def is_cred(key):
    return bool(CRED_RE.search(key) or re.search(r"_(KEY|Key)$", key))


def group_of(key):
    m = re.match(r"ARC_([A-Z0-9]+?)(?:_|$)", key)
    return m.group(1) if m else "OTHER"


def parse_glbcfg(path):
    """返回 [(key, value)]，保持文件顺序"""
    out = []
    for line in pathlib.Path(path).read_text("latin1").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out.append((k.strip(), v.strip()))
    return out


def cmd_glbcfg(a):
    path = pathlib.Path(a.glbcfg)
    items = parse_glbcfg(path)
    print("文件: %s   字段 %d 个" % (path, len(items)))

    groups = {}
    for k, _ in items:
        groups[group_of(k)] = groups.get(group_of(k), 0) + 1
    print("\n按模块统计:")
    for k, v in sorted(groups.items(), key=lambda x: -x[1]):
        print("    %-12s %4d" % (k, v))

    creds = [(k, v) for k, v in items if is_cred(k)]
    print("\n★ 凭据类字段 %d 个（空值=出厂未设置）:" % len(creds))
    for k, v in creds:
        shown = v if v else "（空）"
        print("    %-52s %s" % (k, shown))

    # 备份加密参数
    for k, v in items:
        if k == "ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType":
            print("\n★ web 备份加密算法: %s（解密时还要 -md md5）" % v)

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("key\tvalue\tmodule\n")
            for k, v in items:
                f.write("%s\t%s\t%s\n" % (k, v, group_of(k)))
        print("\n→ 字段表 %s" % a.out)
    return 0


# ───────────────────────── ① rootfs ─────────────────────────

def cmd_rootfs(a):
    root = pathlib.Path(a.rootfs)
    if not root.is_dir():
        print("✗ 不是目录: %s" % root)
        return 1

    # 配置包位置（Arcadyan 的标准布局）
    pack = None
    for p in (root / "usr/share/config/etc", root / "etc"):
        if (p / "config").is_dir() or (p / "passwd").is_file():
            pack = p
            break

    print("rootfs: %s" % root)
    if pack:
        n = sum(1 for _ in pack.rglob("*") if _.is_file())
        print("★ 配置包: %s（%d 个文件）" % (pack, n))
        print("  启动时由 sysup 执行: cp -af /usr/share/config/etc/* /etc")
    else:
        print("⚠ 没找到配置包目录（可能不是 Arcadyan rootfs）")

    def show(title, pats, limit=40):
        """pats 里的项：以 . 开头的是后缀，其余按完整文件名/前缀"""
        print("\n%s" % title)
        hits = []
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if any((fn.endswith(p) if p.startswith(".") else fn == p)
                       for p in pats):
                    fp = pathlib.Path(dirpath) / fn
                    try:
                        hits.append((fp.stat().st_size, fp))
                    except OSError:
                        pass
        for size, fp in sorted(hits)[:limit]:
            print("    %8d  %s" % (size, fp.relative_to(root)))
        if not hits:
            print("    （无）")
        return hits

    show("★ 口令/账号文件", ["passwd", "shadow", "group", "smbpasswd", "authorized_keys"])
    show("★ 密钥/证书", [".pem", ".key", ".crt", "dropbear_"])
    show("★ 各类 secrets", ["ipsec.secrets", "psk.txt", "chap-secrets", "xl2tp-secrets"])

    print("\n★ 服务侧配置（凭据常藏在这里）")
    base = pack or root
    for name in ("samba", "openvpn", "pptpd.conf", "xl2tpd.conf", "dropbear",
                 "miniupnpd.conf", "upnpd", "settings.json", "pslist.conf"):
        for fp in base.rglob(name):
            print("    %s" % fp.relative_to(root))

    glb = None
    for fp in root.rglob(".glbcfg"):
        glb = fp
        break
    if glb:
        items = parse_glbcfg(glb)
        creds = [(k, v) for k, v in items if is_cred(k)]
        print("\n★ %s：%d 字段，其中凭据类 %d 个" % (glb.relative_to(root), len(items), len(creds)))
        print("   （用 `cfgpack.py glbcfg %s` 看明细）" % glb)
        for k, v in items:
            if k == "ARC_SYS_Password":
                print("   ARC_SYS_Password = %r  ← 出厂明文口令" % v)
            if k == "ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType":
                print("   web 备份算法     = %r" % v)

    # passwd 里的哈希类型
    pw = None
    for fp in root.rglob("passwd"):
        if fp.is_file() and "config" in str(fp):
            pw = fp
            break
    if pw:
        print("\n★ %s 内容:" % pw.relative_to(root))
        for line in pw.read_text(errors="replace").splitlines():
            print("    " + line)
        print("  $1$…  = MD5-crypt；$5$… = SHA256-crypt；$6$… = SHA512-crypt；!/* = 锁定")
    return 0


# ───────────────────── ③ web 备份解密/打包 ─────────────────────

def _openssl(decrypt, src, dst):
    args = ["openssl", "enc", "-" + WEB_CIPHER, "-md", WEB_DIGEST, "-salt", "-a",
            "-pass", "stdin", "-in", str(src), "-out", str(dst)]
    if decrypt:
        args.insert(2, "-d")
    r = subprocess.run(args, input=(WEB_KEY + "\n").encode(),
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip())
    return dst


def _safe_extract(tf, dest):
    dest = pathlib.Path(dest).resolve()
    for m in tf.getmembers():
        p = (dest / m.name).resolve()
        if not str(p).startswith(str(dest) + os.sep) and p != dest:
            raise RuntimeError("tar 里有越界路径: %s" % m.name)
    tf.extractall(dest)


def cmd_decrypt(a):
    src = pathlib.Path(a.backup)
    out = pathlib.Path(a.out or (src.stem + "-decoded"))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cfgpack_"))
    tgz = tmp / "config.tgz"
    try:
        _openssl(True, src, tgz)
        print("★ 解密成功（%s / -md %s / -k %s）"
              % (WEB_CIPHER, WEB_DIGEST, WEB_KEY))
        with tarfile.open(tgz, "r:gz") as tf:
            _safe_extract(tf, out)
        print("→ %s" % out)
        for fp in sorted(out.rglob("*")):
            if fp.is_file():
                print("    %8d  %s" % (fp.stat().st_size, fp.relative_to(out)))
    except Exception as e:
        print("✗ 解密/解包失败: %s" % e)
        print("  · 先试探文件头是不是 'Salted__'（openssl 加盐格式）")
        print("  · 老固件可能是 des3，检查 ARC_PROJ_HTTPD_CONFIG_SSL_EncrptType")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


def cmd_pack(a):
    src = pathlib.Path(a.dir)
    out = pathlib.Path(a.out or "Settings.CFG")
    if not src.is_dir():
        print("✗ 不是目录: %s" % src)
        return 1
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cfgpack_"))
    try:
        tgz = tmp / "config.tgz"
        with tarfile.open(tgz, "w:gz") as tf:
            # 与设备一致：把配置目录的内容放在 config/ 下
            for item in sorted(src.iterdir()):
                tf.add(item, arcname="config/" + item.name)
        _openssl(False, tgz, out)
        print("★ 已生成恢复文件: %s（%d 字节）" % (out, out.stat().st_size))
        print("  上传路径: 系统 → 备份/恢复 → 恢复，或 upload.cgi cmd=SYS_PROF")
    except Exception as e:
        print("✗ 打包失败: %s" % e)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


# ───────────────────── ④ flash dump 里捞配置 ─────────────────────

def cmd_carve(a):
    blob = pathlib.Path(a.image).read_bytes()
    out = pathlib.Path(a.out or "cfgpack-carved")
    out.mkdir(parents=True, exist_ok=True)
    print("镜像 %s（%d 字节），扫描 gzip 流…" % (a.image, len(blob)))

    found = 0
    i = 0
    while True:
        i = blob.find(b"\x1f\x8b\x08", i)
        if i < 0:
            break
        try:
            d = zlib.decompressobj(31)
            data = d.decompress(blob[i:i + 32 * 1024 * 1024])
            data += d.flush()
        except Exception:
            i += 1
            continue
        # tar 头校验（ustar 魔数在 257 处）
        if len(data) > 512 and data[257:262] in (b"ustar", b"ustar"):
            try:
                import io
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
                    names = tf.getnames()
            except Exception:
                i += 1
                continue
            if any("glbcfg" in n for n in names):
                dst = out / ("config-%08x.tgz" % i)
                dst.write_bytes(blob[i:i + len(data)])
                found += 1
                print("★ 0x%08X 命中配置 tar（%d 字节，%d 个条目）→ %s"
                      % (i, len(data), len(names), dst))
                sub = out / ("config-%08x" % i)
                sub.mkdir(exist_ok=True)
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
                    _safe_extract(tf, sub)
                for n in names[:12]:
                    print("      " + n)
        i += 1

    if not found:
        print("✗ 没扫到含 .glbcfg 的 tar.gz。")
        print("  提示：先确认 dump 覆盖了 pricfg 分区；配置也可能在 /data（jffs2）里，")
        print("        用 jffs2_extract.py 解那一块。")
        return 1
    print("\n→ %s（共 %d 个）" % (out, found))
    return 0


# ───────────────────────── main ─────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Arcadyan/Singtel 配置恢复包工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("rootfs", help="分析解包后的 rootfs")
    p.add_argument("rootfs")
    p.set_defaults(func=cmd_rootfs)

    p = sub.add_parser("glbcfg", help="解析 .glbcfg 字段与凭据")
    p.add_argument("glbcfg")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_glbcfg)

    p = sub.add_parser("decrypt", help="离线解密 web 备份 Settings.CFG")
    p.add_argument("backup")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_decrypt)

    p = sub.add_parser("pack", help="把配置目录打包成可恢复的 Settings.CFG")
    p.add_argument("dir")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("carve", help="从 flash dump 里捞配置 tar.gz")
    p.add_argument("image")
    p.add_argument("-o", "--out")
    p.set_defaults(func=cmd_carve)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
