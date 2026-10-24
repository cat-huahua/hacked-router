"""Loopback-only protocol tests; no device or production service is contacted."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location('server', Path(__file__).resolve().parents[1] / 'autofw_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = module.ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
        self.server.firmware = None
        self.server.version = 'synthetic-version'
        self.server.image_url = 'http://127.0.0.1/firmware.bin'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def post(self, path, data):
        request = Request(self.base + path, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=3) as response:
            return json.load(response)

    def test_no_update_by_default(self):
        self.assertEqual(self.post('/GetFirmwareVersion', {'Serial Number': 'synthetic', 'Product Class': 'synthetic', 'Current Version': 'synthetic'}), {'Result': 2})

    def test_offer_and_download_exact_bytes(self):
        image = Path(self.temp.name) / 'fixture.bin'
        image.write_bytes(bytes(range(256)))
        self.server.firmware = image
        result = self.post('/GetFirmwareVersion', {'Serial Number': 'synthetic', 'Product Class': 'synthetic', 'Current Version': 'synthetic'})
        self.assertEqual(result, {'Result': 0, 'New Version': self.server.version, 'Image Location': self.server.image_url})
        with urlopen(self.base + '/firmware.bin', timeout=3) as response:
            self.assertEqual(response.read(), image.read_bytes())
        self.assertEqual(self.post('/FirmwareDownloadResult', {'Result': 0}), {'Result': 0})

    def test_invalid_schema_and_path_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.post('/GetFirmwareVersion', {})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + '/../../etc/passwd', timeout=3)
        self.assertEqual(error.exception.code, 404)
        error.exception.close()
