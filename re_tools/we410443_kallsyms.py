#!/usr/bin/env python3
"""Decode the verified WE410443-ST build14 kernel kallsyms tables, offline.

The fixed offsets are intentionally bound to an exact input digest. Outputs
belong in private storage; this recovers symbols, not original source code.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import struct

SHA256 = '9ccc2e7356de88658bbd1c905035695fc032f4784e697ec28cc3cc5c2cd4fb7a'
BASE = 0x81001000
OFFSETS = dict(addresses=0x55a140, num_syms=0x57a380, names=0x57a390,
               names_end=0x5d8d87, markers=0x5d8d90,
               token_table=0x5d8fa0, token_index=0x5d9320)


def decode(data):
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('Input does not match the verified build14 raw kernel')
    count, = struct.unpack_from('<I', data, OFFSETS['num_syms'])
    if count != 32911:
        raise ValueError('Unexpected symbol count')
    addresses = struct.unpack_from(f'<{count}I', data, OFFSETS['addresses'])
    if list(addresses) != sorted(addresses):
        raise ValueError('Addresses are not monotonic')
    indices = struct.unpack_from('<256H', data, OFFSETS['token_index'])
    tokens, cursor = [], OFFSETS['token_table']
    for offset in indices:
        if cursor != OFFSETS['token_table'] + offset:
            raise ValueError('Token index does not match token boundary')
        end = data.index(b'\0', cursor, OFFSETS['token_index'])
        tokens.append(data[cursor:end])
        cursor = end + 1
    rows, marker_offsets, cursor = [], [], OFFSETS['names']
    for ordinal, address in enumerate(addresses):
        if ordinal % 256 == 0:
            marker_offsets.append(cursor - OFFSETS['names'])
        name_offset = cursor
        length = data[cursor]
        cursor += 1
        name = b''.join(tokens[b] for b in data[cursor:cursor + length]).decode('ascii')
        cursor += length
        if len(name) < 2 or any(not 33 <= ord(c) <= 126 for c in name):
            raise ValueError('Invalid expanded symbol')
        rows.append(dict(ordinal=ordinal, address=f'{address:08x}', type=name[0],
                         name=name[1:], name_file_offset=name_offset,
                         file_backed=BASE <= address < BASE + len(data)))
    if cursor != OFFSETS['names_end']:
        raise ValueError('Names did not end at the verified boundary')
    markers = struct.unpack_from(f'<{len(marker_offsets)}I', data, OFFSETS['markers'])
    if list(markers) != marker_offsets:
        raise ValueError('Marker offsets do not match decoded names')
    if [(r['address'], r['name']) for r in rows[:3]] != [
            ('81001000', '_text'), ('81001400', 'run_init_process'), ('81001400', '_stext')]:
        raise ValueError('Initial address/name pairing does not match')
    if (rows[-1]['type'], rows[-1]['name']) != ('b', 'klist_remove_lock'):
        raise ValueError('Unexpected final symbol')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if any((p / '.git').exists() for p in (output, *output.parents)):
        parser.error('Output must be outside Git')
    rows = decode(args.kernel.read_bytes())
    os.umask(0o077)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    (output / 'symbols.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (output / 'symbols.tsv').write_text(''.join(
        f"{r['address']}\t{r['type']}\t{r['name']}\n" for r in rows))
    summary = dict(input_sha256=SHA256, image_base=f'{BASE:08x}', offsets=OFFSETS,
                   symbols=len(rows), types=dict(Counter(r['type'] for r in rows)),
                   unique_addresses=len({r['address'] for r in rows}),
                   text_symbols=sum(r['type'] in 'Tt' for r in rows),
                   file_backed_text_addresses=len({r['address'] for r in rows
                       if r['type'] in 'Tt' and r['file_backed']}),
                   markers_verified=129, all_machine_code_proven_covered=False)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
