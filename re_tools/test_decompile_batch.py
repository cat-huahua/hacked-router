"""Ledger integration checks using a fake headless exporter, never firmware.

These tests exercise process completion and partial/missing evidence. They do
not establish that Ghidra can decode an architecture or recover all functions.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('decompile_batch', Path(__file__).with_name('decompile_batch.py'))
BATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BATCH)
REAL_SLEEP = time.sleep

FAKE_HEADLESS = '''#!/usr/bin/env python3
import sys, json, hashlib, time
from pathlib import Path
args = sys.argv[1:]
stage = Path(args[args.index('-import') + 1])
output = Path(args[args.index('-postScript') + 2])
for source in stage.iterdir():
    data = source.read_bytes()
    mode = data[4:].decode()
    if mode == 'linger':
        time.sleep(60)
    digest = hashlib.sha256(data).hexdigest()
    case = output / digest
    case.mkdir()
    if mode == 'missing_summary':
        continue
    summary = dict(input_sha256=digest, recognized_functions=2,
                   decompiled_functions=2, failed_functions=0,
                   analysis_timed_out=False)
    if mode == 'timeout':
        summary['analysis_timed_out'] = True
    if mode == 'function_failure':
        summary.update(decompiled_functions=1, failed_functions=1)
    if mode == 'bad_counts':
        summary['decompiled_functions'] = 0
    if mode == 'digest_mismatch':
        summary['input_sha256'] = '0' * 64
    if mode != 'missing_artifacts':
        (case / 'functions.jsonl').write_text(''.join(
            json.dumps(dict(address=str(i), decompiled=i < summary['decompiled_functions'])) + '\\n'
            for i in range(2)))
        (case / 'pseudocode.c').write_text('/* fake export */\\n')
        (case / 'assembly.txt').write_text('# fake export\\n')
    (case / 'summary.json').write_text(json.dumps(summary))
    if mode == 'process_failure':
        sys.exit(3)
'''


class BatchLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='firmware-ledger-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ghidra = self.root / 'fake-ghidra'
        (self.ghidra / 'support').mkdir(parents=True)
        headless = self.ghidra / 'support/analyzeHeadless'
        headless.write_text(FAKE_HEADLESS)
        headless.chmod(0o700)

    def export(self, mode):
        inputs = self.root / 'inputs'
        inputs.mkdir()
        (inputs / 'sample').write_bytes(b'\x7fELF' + mode.encode())
        output = self.root / 'evidence'
        with patch.object(BATCH.time, 'sleep', lambda _: REAL_SLEEP(.02)):
            status = BATCH.run([inputs], output, self.ghidra, None, 2, 10)
        ledger = json.loads((output / 'completed.json').read_text())
        self.assertFalse(ledger['all_machine_code_proven_covered'])
        return status, ledger

    def test_success(self):
        status, ledger = self.export('success')
        self.assertEqual(status, 0)
        self.assertEqual(ledger['modules'][0]['status'], 'exported')

    def test_existing_output_is_not_overwritten(self):
        inputs = self.root / 'inputs'
        inputs.mkdir()
        output = self.root / 'evidence'
        output.mkdir()
        existing = output / 'headless-0.log'
        existing.write_text('previous unrelated evidence')
        with self.assertRaisesRegex(ValueError, 'new batch directory'):
            BATCH.run([inputs], output, self.ghidra, None, 1, 10)
        self.assertEqual(existing.read_text(), 'previous unrelated evidence')

    def test_analysis_timeout_is_partial(self):
        status, ledger = self.export('timeout')
        self.assertEqual(status, 1)
        self.assertEqual(ledger['modules'][0]['status'], 'partial')

    def test_function_failure_is_partial(self):
        status, ledger = self.export('function_failure')
        self.assertEqual(status, 1)
        self.assertEqual(ledger['modules'][0]['status'], 'partial')

    def test_missing_summary_is_terminal_failure(self):
        status, ledger = self.export('missing_summary')
        self.assertEqual(status, 1)
        self.assertEqual(ledger['modules'][0]['status'], 'missing_export')

    def test_missing_artifacts_fail(self):
        status, ledger = self.export('missing_artifacts')
        self.assertEqual(status, 1)
        self.assertEqual(ledger['modules'][0]['status'], 'missing_artifacts')

    def test_inconsistent_function_counts_fail(self):
        status, ledger = self.export('bad_counts')
        self.assertEqual(status, 1)
        self.assertNotEqual(ledger['modules'][0]['status'], 'exported')

    def test_input_digest_mismatch_fails(self):
        status, ledger = self.export('digest_mismatch')
        self.assertEqual(status, 1)
        self.assertEqual(ledger['modules'][0]['status'], 'digest_mismatch')

    def test_shard_failure_is_not_hidden_by_complete_export(self):
        status, ledger = self.export('process_failure')
        self.assertEqual(status, 1)
        self.assertEqual(ledger['processes'][0]['exit_code'], 3)

    def test_incomplete_json_at_end_is_explicit_failure(self):
        output = self.root / 'evidence'
        case = output / 'modules' / 'abc'
        case.mkdir(parents=True)
        (case / 'summary.json').write_text('{"input_sha256":')

        class FinishedProcess:
            pid = 123
            def poll(self):
                return 0

        ledger = BATCH.checkpoint(output, [dict(sha256='abc')], [FinishedProcess()])
        self.assertEqual(ledger['modules'][0]['status'], 'invalid_summary')

    def test_checkpoint_exception_cleans_up_owned_process(self):
        inputs = self.root / 'inputs'
        inputs.mkdir()
        (inputs / 'sample').write_bytes(b'\x7fELFlinger')
        started = []
        real_popen = BATCH.subprocess.Popen

        def capture_process(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            started.append(process)
            return process

        try:
            with patch.object(BATCH.subprocess, 'Popen', capture_process), \
                 patch.object(BATCH, 'checkpoint', side_effect=RuntimeError('simulated ledger failure')):
                with self.assertRaisesRegex(RuntimeError, 'simulated ledger failure'):
                    BATCH.run([inputs], self.root / 'evidence', self.ghidra, None, 1, 10)
            self.assertEqual(len(started), 1)
            self.assertIsNotNone(started[0].poll(), 'failed batch left its headless child running')
        finally:
            # Test cleanup still runs if the regression is reintroduced.
            for process in started:
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    unittest.main()
