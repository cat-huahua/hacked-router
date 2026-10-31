#!/usr/bin/env python3
"""Prepare verified WE410443 OpenWrt images and observe a recovery HTTP service.

No password guessing, firmware upload, DNS changes, flash or bootloader writes.
See docs/singtel-openwrt-recovery.md for the still-unverified first-install path.
"""
import argparse
import hashlib
from http.client import HTTPException
import json
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit

BASE = 'https://downloads.openwrt.org/releases/25.12.6/targets/ramips/mt7621/'
IMAGES = {
    'openwrt-25.12.6-ramips-mt7621-arcadyan_we410443-initramfs-kernel.bin':
        ('98d8e06e6d5ecbc4924ec7aee3267de7876482d04ee7c7b4546c51ed5c9a36ba', 7923587),
    'openwrt-25.12.6-ramips-mt7621-arcadyan_we410443-squashfs-sysupgrade.bin':
        ('7efd576e3bb792b849077e29454bd8455f90e8313d656853dc68e8f81917cddb', 9241136),
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def prepare(directory):
    directory = Path(directory).absolute()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest = []
    for name, (expected, size) in IMAGES.items():
        destination = directory / name
        if destination.is_symlink():
            raise ValueError('refusing symlink destination')
        if destination.exists():
            if destination.stat().st_size != size or hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
                raise ValueError('existing image does not match pinned size/SHA256')
        else:
            temporary = directory / (name + '.partial')
            created = False
            try:
                digest, total = hashlib.sha256(), 0
                with temporary.open('xb') as output:
                    created = True
                    with build_opener(NoRedirect).open(BASE + name, timeout=30) as response:
                        if response.status != 200:
                            raise ValueError('download requires HTTP 200')
                        while block := response.read(65536):
                            total += len(block)
                            if total > size:
                                raise ValueError('download exceeds pinned size')
                            digest.update(block)
                            output.write(block)
                if total != size or digest.hexdigest() != expected:
                    raise ValueError('download failed pinned size/SHA256 verification')
                temporary.rename(destination)
            finally:
                # Never remove a pre-existing partial file owned by another run.
                if created and temporary.exists():
                    temporary.unlink()
        manifest.append({'file': name, 'sha256': expected, 'bytes': size})
        print('Verified:', name, flush=True)
    return manifest


def observe(url, timeout, interval, output):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('provide an HTTP(S) URL without credentials or fragment')
    if timeout <= 0 or interval <= 0:
        raise ValueError('timeout and interval must be positive')
    deadline = time.monotonic() + timeout
    opener = build_opener(NoRedirect)
    attempts = 0
    while True:
        attempts += 1
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('no HTTP 200 observed within the deadline')
            request = Request(url, headers={'User-Agent': 'WE410443-recovery-observer/1'})
            with opener.open(request, timeout=min(3, remaining)) as response:
                if response.status != 200:
                    raise URLError('waiting for HTTP 200')
                body = response.read(262145)
                if len(body) > 262144:
                    raise ValueError('page exceeds observation limit')
        except (URLError, OSError, HTTPException):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('no HTTP 200 observed within the deadline')
            time.sleep(min(interval, remaining))
            continue
        if output:
            with Path(output).open('xb') as page:
                page.write(body)
        return {'http_status': 200, 'attempts': attempts,
                'body_sha256': hashlib.sha256(body).hexdigest(),
                'bytes': len(body), 'recovery_verified': False, 'flashed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_parser = commands.add_parser('prepare', help='download and verify official images')
    prepare_parser.add_argument('directory', help='private output outside this repository')
    watch = commands.add_parser('watch', help='bounded GET polling; never uploads firmware')
    watch.add_argument('--url', required=True, help='observed isolated device URL; not a guessed default')
    watch.add_argument('--timeout', type=float, default=300)
    watch.add_argument('--interval', type=float, default=2)
    watch.add_argument('--save-page', help='new private file; page may contain device identity')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.directory)
        else:
            result = observe(args.url, args.timeout, args.interval, args.save_page)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, URLError, HTTPException) as error:
        parser.exit(1, f'Failed: {error}\n')


if __name__ == '__main__':
    main()
