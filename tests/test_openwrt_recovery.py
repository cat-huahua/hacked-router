"""Host-only tests: no router contact, production uploads or flash commands."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recovery', ROOT / 'openwrt/recovery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Page(BaseHTTPRequestHandler):
    methods = []

    def do_GET(self):
        self.methods.append('GET')
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'<html>synthetic page, not proof of recovery</html>')

    def log_message(self, *args):
        pass


class RecoveryTests(unittest.TestCase):
    def test_watch_observes_without_claiming_recovery_or_posting(self):
        Page.methods = []
        server = ThreadingHTTPServer(('127.0.0.1', 0), Page)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = module.observe(f'http://127.0.0.1:{server.server_port}/', 2, .01, None)
            self.assertEqual(result['http_status'], 200)
            self.assertFalse(result['recovery_verified'])
            self.assertFalse(result['flashed'])
            self.assertEqual(Page.methods, ['GET'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_bounded_timeout_and_url_validation(self):
        with self.assertRaises(TimeoutError):
            module.observe('http://127.0.0.1:1/', .03, .01, None)
        with self.assertRaises(ValueError):
            module.observe('file:///etc/passwd', 1, 1, None)

    def test_pinned_download_and_wrong_digest(self):
        body = b'synthetic bytes'
        assets = {'fixture.bin': (hashlib.sha256(body).hexdigest(), len(body))}

        class Response(io.BytesIO):
            status = 200

        class Opener:
            def open(self, *args, **kwargs):
                return Response(body)

        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'IMAGES', assets), patch.object(module, 'build_opener', return_value=Opener()):
            module.prepare(directory)
            self.assertEqual((Path(directory) / 'fixture.bin').read_bytes(), body)
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'IMAGES', {'fixture.bin': ('0' * 64, len(body))}), patch.object(module, 'build_opener', return_value=Opener()):
            with self.assertRaises(ValueError):
                module.prepare(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_preexisting_partial_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(module, 'IMAGES', {'fixture.bin': ('0' * 64, 1)}):
            partial = Path(directory) / 'fixture.bin.partial'
            partial.write_bytes(b'existing owner data')
            with self.assertRaises(FileExistsError):
                module.prepare(directory)
            self.assertEqual(partial.read_bytes(), b'existing owner data')


class PersistenceTests(unittest.TestCase):
    def fixture(self, base, overlay='jffs2'):
        (base / 'tmp/sysinfo').mkdir(parents=True)
        (base / 'tmp/sysinfo/board_name').write_text('arcadyan,we410443\n')
        (base / 'proc').mkdir()
        (base / 'proc/mounts').write_text(f'/dev/root /rom squashfs ro 0 0\n/dev/mtdblock6 /overlay {overlay} rw 0 0\n')
        (base / 'etc/config').mkdir(parents=True)
        (base / 'etc/config/system').write_text("config system\n option hostname 'synthetic'\n")

    def run_script(self, base, command):
        import os
        env = os.environ.copy()
        env['MESH_SETTINGS_ROOT'] = str(base)
        return subprocess.run(['sh', str(ROOT / 'openwrt/mesh-settings'), command], env=env, capture_output=True)

    def test_ram_overlay_and_wrong_board_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.fixture(base, 'tmpfs')
            self.assertNotEqual(self.run_script(base, 'check').returncode, 0)
            (base / 'tmp/sysinfo/board_name').write_text('wrong,board\n')
            self.assertNotEqual(self.run_script(base, 'mark').returncode, 0)
            self.assertFalse((base / 'etc/mesh-persistence').exists())

    def test_baseline_detects_configuration_change(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.fixture(base)
            self.assertEqual(self.run_script(base, 'mark').returncode, 0)
            self.assertEqual(self.run_script(base, 'verify').returncode, 0)
            (base / 'etc/config/system').write_text('changed\n')
            self.assertNotEqual(self.run_script(base, 'verify').returncode, 0)
            self.assertNotEqual(self.run_script(base, 'commit').returncode, 0)
