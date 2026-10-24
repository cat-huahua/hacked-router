#!/usr/bin/env python3
"""Local Arcadyan autofw protocol server; see docs/singtel-extender-autofw.md.

Starts in no-update mode. Offering an image requires --firmware, --version and
--image-url together. Does not configure DNS, modify firmware, or write flash.
Request bodies and device identifiers are not logged.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import ssl
from urllib.parse import urlsplit


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in ('/GetFirmwareVersion', '/FirmwareDownloadResult',
                             '/FirmwareUpgradeResult'):
            self.reply(404, {'Result': 1})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError()
            message = json.loads(self.rfile.read(length))
            if not isinstance(message, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            self.close_connection = True
            self.reply(400, {'Result': 1})
            return
        if self.path != '/GetFirmwareVersion':
            self.reply(200, {'Result': 0})
        elif not all(isinstance(message.get(k), str) for k in
                     ('Serial Number', 'Product Class', 'Current Version')):
            self.reply(400, {'Result': 1})
        elif self.server.firmware is None:
            self.reply(200, {'Result': 2})
        else:
            self.reply(200, {'Result': 0, 'New Version': self.server.version,
                             'Image Location': self.server.image_url})

    def do_GET(self):
        if self.path != '/firmware.bin' or self.server.firmware is None:
            self.reply(404, {'Result': 1})
            return
        with self.server.firmware.open('rb') as image:
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(self.server.firmware.stat().st_size))
            self.end_headers()
            shutil.copyfileobj(image, self.wfile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--firmware', type=Path)
    parser.add_argument('--version')
    parser.add_argument('--image-url', help='reachable absolute URL ending /firmware.bin')
    parser.add_argument('--cert', type=Path)
    parser.add_argument('--key', type=Path)
    args = parser.parse_args()
    offer = (args.firmware is not None, args.version is not None, args.image_url is not None)
    if any(offer) and not all(offer):
        parser.error('--firmware, --version and --image-url must be supplied together')
    if args.firmware is not None and not args.firmware.is_file():
        parser.error('--firmware must be an existing file')
    if args.image_url:
        url = urlsplit(args.image_url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.path != '/firmware.bin' or url.query or url.fragment or url.username or url.password:
            parser.error('--image-url must be an HTTP(S) URL ending /firmware.bin')
    if bool(args.cert) != bool(args.key):
        parser.error('--cert and --key must be supplied together')
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.firmware, server.version, server.image_url = args.firmware, args.version, args.image_url
    if args.cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f'Listening on {args.bind}:{args.port}; image offer={all(offer)}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
