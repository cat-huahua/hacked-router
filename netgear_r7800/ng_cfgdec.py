#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复刻 orbicfg 的 NETGEAR 配置解密（uclibc + musl 两种 PRNG 都试）"""
import struct, sys

DEG3, SEP3 = 31, 3
RANDTBL = [-1726662223,379960547,1735697613,1040273694,1313901226,1627687941,-179304937,
 -2073333483,1780058412,-1989503057,-615974602,344556628,939512070,-1249116260,1507946756,
 -812545463,154635395,1388815473,-1926676823,525320961,-1009028674,968117788,-123449607,
 1284210865,435012392,-2017506339,-911064859,-370259173,1132637927,1398500161,-205601318]

def i32(x): 
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x >= 0x80000000 else x

class Uclibc:
    def __init__(self, seed):
        st = list(RANDTBL); kc = DEG3
        w = seed if seed != 0 else 1
        st[0] = i32(w)
        for i in range(1, kc):
            hi, lo = w // 127773, w % 127773
            w = 16807*lo - 2836*hi
            if w < 0: w += 2147483647
            st[i] = i32(w)
        self.f, self.r, self.st = SEP3, 0, st
        for _ in range(kc*10): self.rand()
    def rand(self):
        v = self.st[self.f] + self.st[self.r]
        self.st[self.f] = i32(v)
        res = (v >> 1) & 0x7fffffff
        self.f += 1
        if self.f >= DEG3: self.f = 0; self.r += 1
        else:
            self.r += 1
            if self.r >= DEG3: self.r = 0
        return res

class Musl:
    def __init__(self, seed):
        self.s = (seed - 1) & 0xFFFFFFFFFFFFFFFF
    def rand(self):
        self.s = (6364136223846793005*self.s + 1) & 0xFFFFFFFFFFFFFFFF
        return i32(self.s >> 33)

def decrypt(path):
    d = open(path, 'rb').read()
    magic, ln, crc = struct.unpack('<III', d[:12])
    print('  %s' % path)
    print('    magic=0x%08X  len=%d  crc=0x%08X  (文件 %d 字节)' % (magic, ln, crc, len(d)))
    body = d[12:12+ln]
    for name, cls in (('uclibc', Uclibc), ('musl', Musl)):
        g = cls(magic)
        out = bytearray()
        for i in range(0, len(body)//4*4, 4):
            v = struct.unpack('<I', body[i:i+4])[0] ^ (g.rand() & 0xFFFFFFFF)
            out += struct.pack('<I', v)
        c = crc
        for i in range(0, len(out)//4*4, 4):
            c = (c + struct.unpack('<I', out[i:i+4])[0]) & 0xFFFFFFFF
        ok = (c == 0xFFFFFFFF)
        print('    %-7s checksum %s' % (name, '★ 通过！' if ok else '不通过'))
        if ok:
            open(path + '.dec.' + name, 'wb').write(bytes(out))
            print('    → 已存 %s.dec.%s (%d 字节)' % (path, name, len(out)))
            print('    前 500 字节:'); print('    ', bytes(out[:500]).decode('utf-8','replace')[:500].replace('\n',' | '))
            return True
    return False

for p in sys.argv[1:]:
    decrypt(p); print()
