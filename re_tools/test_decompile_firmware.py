"""Offline orchestration checks; no Ghidra or target execution required."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from decompile_firmware import export


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'rootfs'
        self.root.mkdir()
        self.output = self.base / 'private'
        self.ghidra = self.base / 'engine'
        support = self.ghidra / 'support'
        support.mkdir(parents=True)
        self.headless = support / 'analyzeHeadless'
        self.headless.write_text('''#!/usr/bin/env python3
import hashlib, json, pathlib, sys
source = pathlib.Path(sys.argv[sys.argv.index('-import') + 1])
out = pathlib.Path(sys.argv[-1])
summary = dict(input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
               recognized_functions=1, decompiled_functions=1, failed_functions=0)
(out / 'summary.json').write_text(json.dumps(summary))
for name in ('pseudocode.c', 'assembly.txt', 'functions.jsonl'):
    (out / name).write_text('test fixture')
''')
        self.headless.chmod(0o700)
        (self.root / 'one').write_bytes(b'\x7fELFtest-one')
        (self.root / 'two').write_bytes(b'\x7fELFtest-one')
        (self.root / 'readme').write_text('ordinary text')

    def run_export(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return export(self.root, self.output, self.ghidra, [], workers=2)

    def test_dedup_resume_and_changed_input(self):
        rows = self.run_export()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum('alias_of' in row for row in rows), 1)
        reused = self.run_export()
        self.assertTrue(next(row for row in reused if 'alias_of' not in row)['reused'])
        (self.root / 'one').write_bytes(b'\x7fELFchanged')
        changed = self.run_export()
        self.assertEqual(len(changed), 2)
        self.assertFalse(any('alias_of' in row for row in changed))
        self.assertEqual(len(json.loads((self.output / 'coverage.json').read_text())), 2)

    def test_failed_rerun_does_not_reuse_stale_summary(self):
        self.run_export()
        (self.root / 'one').write_bytes(b'\x7fELFchanged')
        self.headless.write_text('#!/bin/sh\nexit 1\n')
        rows = self.run_export()
        row = next(row for row in rows if row['path'] == 'one')
        self.assertEqual(row['exit_code'], 1)
        self.assertNotIn('summary', row)

    def test_private_output_and_module_boundaries(self):
        with self.assertRaises(ValueError):
            export(self.root, self.root / 'output', self.ghidra, [])
        public = self.base / 'public'
        (public / '.git').mkdir(parents=True)
        with self.assertRaises(ValueError):
            export(self.root, public / 'output', self.ghidra, [])
        outside = self.base / 'outside'
        outside.write_bytes(b'\x7fELFoutside')
        with self.assertRaises(ValueError):
            export(self.root, self.output, self.ghidra, ['../outside'])


if __name__ == '__main__':
    unittest.main()
