"""Synthetic backup round-trip; no vendor passphrase is embedded."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('cfgpack', Path(__file__).resolve().parents[1] / 'cfgpack.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class KeyFileTests(unittest.TestCase):
    def test_pack_decrypt_roundtrip_without_disclosing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'input'
            source.mkdir()
            (source / '.glbcfg').write_text('ARC_SYS_ModelName=synthetic\n')
            key = base / 'key.txt'
            secret = 'synthetic-test-passphrase'
            key.write_text(secret + '\n')
            backup, output = base / 'Settings.CFG', base / 'output'
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                self.assertEqual(module.cmd_pack(SimpleNamespace(dir=source, out=backup, key_file=key)), 0)
                self.assertEqual(module.cmd_decrypt(SimpleNamespace(backup=backup, out=output, key_file=key)), 0)
            self.assertEqual((output / 'config/.glbcfg').read_bytes(), (source / '.glbcfg').read_bytes())
            self.assertNotIn(secret, log.getvalue())

    def test_empty_or_multiple_passphrases_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / 'key'
            for value in ('', '\n', 'first\nsecond\n'):
                key.write_text(value)
                with self.assertRaises(ValueError):
                    module._openssl(True, 'unused', 'unused', key)
