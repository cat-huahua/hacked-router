"""A retry must match both original provenance and failed function identities."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from report_decompile import verified_retry


class RetryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.module, self.retry = base / 'original', base / 'retry'
        self.module.mkdir(); self.retry.mkdir()
        summary = dict(input_sha256='a' * 64, recognized_functions=2, decompiled_functions=1, failed_functions=1)
        (self.module / 'summary.json').write_text(json.dumps(summary))
        (self.module / 'functions.jsonl').write_text('\n'.join(json.dumps(row) for row in [
            dict(address='1000', decompiled=True), dict(address='2000', decompiled=False)]))
        result = dict(input_sha256='a' * 64, attempted_functions=1, decompiled_functions=1, failed_functions=0,
                      source_summary_sha256=self.digest('summary.json'), source_index_sha256=self.digest('functions.jsonl'))
        (self.retry / 'retry-summary.json').write_text(json.dumps(result))
        (self.retry / 'retry-functions.jsonl').write_text(json.dumps(dict(address='2000', decompiled=True)))
        (self.retry / 'retry-pseudocode.c').write_text('/* synthetic test output */')

    def digest(self, name):
        return hashlib.sha256((self.module / name).read_bytes()).hexdigest()

    def test_matching_recovery(self):
        self.assertEqual(verified_retry(self.module, self.retry)['decompiled_functions'], 1)

    def test_changed_original_is_rejected(self):
        (self.module / 'functions.jsonl').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            verified_retry(self.module, self.retry)

    def test_wrong_function_is_rejected(self):
        (self.retry / 'retry-functions.jsonl').write_text(json.dumps(dict(address='3000', decompiled=True)))
        with self.assertRaisesRegex(ValueError, 'original failed entries'):
            verified_retry(self.module, self.retry)


if __name__ == '__main__':
    unittest.main()
