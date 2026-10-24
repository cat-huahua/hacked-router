#!/usr/bin/env python3
"""Extract Arcadyan's byte-obfuscated XZ squashfs without running firmware.

Requires a host C compiler, liblzma development headers, and unsquashfs.
Outputs can contain credentials: choose a private directory outside this repo.
This is an extractor, not a firmware image builder or flasher.
"""
import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


def extract(image, destination):
    image = Path(image).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination must not exist')
    with image.open('rb') as stream:
        header = stream.read(96)
    if len(header) != 96 or header[:4] != b'hsqs':
        raise ValueError('input must be an extracted little-endian squashfs')
    if struct.unpack_from('<H', header, 20)[0] != 4:
        raise ValueError('only XZ squashfs (compressor 4) is supported')
    used = struct.unpack_from('<Q', header, 40)[0]
    if not 96 <= used <= image.stat().st_size:
        raise ValueError('invalid squashfs bytes_used')
    compiler, unsquashfs = shutil.which('cc'), shutil.which('unsquashfs')
    if not compiler or not unsquashfs:
        raise ValueError('cc and unsquashfs are required')
    source = Path(__file__).resolve().with_name('arc_xz_shim.c')
    with tempfile.TemporaryDirectory(prefix='arc-xz-') as scratch:
        shim = str(Path(scratch) / 'arc_xz_shim.so')
        subprocess.run([compiler, '-shared', '-fPIC', '-O2', '-Wall', '-Wextra',
                        '-o', shim, str(source), '-ldl'], check=True)
        env = os.environ.copy()
        env['LD_PRELOAD'] = shim
        subprocess.run([unsquashfs, '-no-progress', '-processors', '1',
                        '-d', str(destination), str(image)], env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', help='extracted squashfs, not the .trx container')
    parser.add_argument('destination', help='new private output directory')
    args = parser.parse_args()
    try:
        extract(args.image, args.destination)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Extraction failed: {error}\n')


if __name__ == '__main__':
    main()
