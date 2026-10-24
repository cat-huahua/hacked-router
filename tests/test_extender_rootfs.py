"""Exercise the host shim with synthetic streams, without firmware or keys."""
import lzma
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def output_byte(v):
    if not v & 1:
        v ^= 0xda
    if v & 0x80:
        v ^= 0x55
    return v ^ {0: 0x76, 8: 0x5e, 0x20: 0xab, 0x28: 0xd5}[v & 0x28]


class ShimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.base = Path(cls.scratch.name)
        cls.shim = cls.base / 'shim.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-o', str(cls.shim),
                        str(ROOT / 'arc_xz_shim.c'), '-ldl'], check=True)
        harness = cls.base / 'decode.c'
        harness.write_text('''#include <lzma.h>
#include <stdio.h>
#include <stdint.h>
int main(void) {
 unsigned char in[65536], out[65536];
 size_t n=fread(in,1,sizeof(in),stdin), ip=0, op=0;
 uint64_t limit=UINT64_MAX;
 lzma_ret r=lzma_stream_buffer_decode(&limit,0,NULL,in,&ip,n,out,&op,sizeof(out));
 if(r!=LZMA_OK)return 1;
 return fwrite(out,1,op,stdout)==op?0:2;
}
''')
        cls.exe = cls.base / 'decode'
        subprocess.run(['cc', '-o', str(cls.exe), str(harness), '-llzma'], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def decode(self, stream):
        env = os.environ.copy()
        env['LD_PRELOAD'] = str(self.shim)
        return subprocess.run([str(self.exe)], input=stream, capture_output=True, env=env)

    def test_vendor_layers_restore_all_byte_values(self):
        plain = bytes(range(256)) * 32
        inverse = bytearray(256)
        self.assertEqual(len({output_byte(v) for v in range(256)}), 256)
        for v in range(256):
            inverse[output_byte(v)] = v
        xz = lzma.compress(plain.translate(bytes(inverse)))
        encoded = bytes((((v << 3) | (v >> 5)) & 255) ^ 0x45 for v in xz)
        result = self.decode(encoded)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, plain)

    def test_standard_xz_is_unchanged(self):
        plain = b'standard host XZ stream' * 40
        result = self.decode(lzma.compress(plain))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, plain)

    def test_corrupt_stream_fails(self):
        result = self.decode(bytes.fromhex('aafc96879745') + b'broken stream')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
