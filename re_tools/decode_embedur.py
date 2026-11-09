#!/usr/bin/env python3
"""Statically decode the WE410443-ST build14 embedded agent into private storage.

The 256-byte substitution table is read from the verified arc_swap ELF, never
executed. Output includes firmware credentials and must remain outside Git.
"""
import argparse
import bz2
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile

ARC_SWAP_SHA256 = '4d34d38795f353519aeb417e10617efe0dd3341f3baa5a83c95de504a006bc58'
TABLE_OFFSET = 0xbe0
LIMIT = 64 * 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def decode(rootfs, output):
    rootfs = Path(rootfs).resolve(strict=True)
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(rootfs):
        raise ValueError('output must be new and outside input rootfs')
    if any((p / '.git').exists() for p in (output, *output.parents)):
        raise ValueError('output must be outside Git')

    def read(relative, limit):
        path = (rootfs / relative).resolve(strict=True)
        if not path.is_relative_to(rootfs) or path.stat().st_size > limit:
            raise ValueError('input outside rootfs or exceeds size limit')
        return path.read_bytes()

    binary = read('sbin/arc_swap', LIMIT)
    if sha256(binary) != ARC_SWAP_SHA256:
        raise ValueError('unrecognized arc_swap build; re-establish its table offset first')
    table = binary[TABLE_OFFSET:TABLE_OFFSET + 256]
    if len(set(table)) != 256:
        raise ValueError('substitution table is not a byte permutation')
    encoded = read('usr/bin/embedur/erm_agent.tar.bz2', LIMIT)
    checksum = read('usr/bin/embedur/erm_agent.tar.bz2.sha256sum', 4096)
    match = re.match(rb'^([0-9a-fA-F]{64})\s', checksum)
    if not match:
        raise ValueError('invalid packaged SHA-256 checksum')
    decoded = encoded.translate(table)
    if sha256(decoded) != match[1].decode().lower():
        raise ValueError('decoded archive does not match packaged SHA-256')
    decompressor = bz2.BZ2Decompressor()
    plain = decompressor.decompress(decoded, max_length=LIMIT)
    if not decompressor.eof or decompressor.unused_data:
        raise ValueError('oversized, truncated or trailing BZip2 data')

    rows, payloads, seen = [], [], set()
    with tarfile.open(fileobj=io.BytesIO(plain), mode='r:') as archive:
        total = 0
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or '\\' in member.name:
                raise ValueError('unsafe archive path')
            name = str(path)
            if name in seen or len(seen) >= 10000:
                raise ValueError('duplicate path or too many archive members')
            seen.add(name)
            if not (member.isdir() or member.isfile()):
                raise ValueError('links and special archive entries are not accepted')
            total += member.size
            if member.size < 0 or total > LIMIT:
                raise ValueError('archive payload limit exceeded')
            row = {'path': name, 'size': member.size, 'type': 'directory' if member.isdir() else 'file'}
            content = None
            if member.isfile():
                with archive.extractfile(member) as stream:
                    content = stream.read(LIMIT + 1)
                if len(content) != member.size:
                    raise ValueError('archive member size mismatch')
                row.update(sha256=sha256(content), elf=content.startswith(b'\x7fELF'))
            rows.append(row)
            payloads.append((path, content))
    file_names = {str(path) for path, content in payloads if content is not None}
    if any(str(parent) in file_names for path, _ in payloads for parent in path.parents):
        raise ValueError('file and parent-directory conflict')

    os.umask(0o077)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    extracted = output / 'root'
    extracted.mkdir()
    for path, content in payloads:
        destination = extracted.joinpath(*path.parts)
        if content is None:
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(content)
    (output / 'decoded.tar.bz2').write_bytes(decoded)
    summary = {
        'input_sha256': sha256(encoded), 'arc_swap_sha256': sha256(binary),
        'table_file_offset': hex(TABLE_OFFSET), 'decoded_sha256': sha256(decoded),
        'matches_packaged_checksum': True, 'tar_bytes': len(plain),
        'members': len(rows), 'files': sum(r['type'] == 'file' for r in rows),
        'elf_files': sum(r.get('elf', False) for r in rows),
        'target_code_executed': False,
    }
    (output / 'members.json').write_text(json.dumps(rows, indent=2))
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rootfs')
    parser.add_argument('output', help='new private directory, outside Git')
    args = parser.parse_args()
    try:
        result = decode(args.rootfs, args.output)
    except (OSError, ValueError, EOFError, tarfile.TarError) as error:
        parser.exit(1, f'Decode failed: {error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
