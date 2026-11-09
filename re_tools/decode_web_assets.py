#!/usr/bin/env python3
"""Statically decode verified firmware web wrappers without executing JavaScript.

Recognizes two exact Dean Edwards packer boilerplates and the verified
WE410443-ST global.js template. Unknown wrappers remain unchanged and explicit.
Decoded output may contain credentials; it must remain outside Git/input trees.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re

PACKERS = {
    'd810e4e892e4077e9e0d6da26e85ff581e9fa5f1b6db8223230c3885d590f586': 36,
    '6e5d9bc2946ce47f6435df2287da147abb30cb851d3e00ff35ae66c6a25a52d4': 62,
}
# Hash of the entire verified global.js with only its payload replaced. This
# deliberately rejects changes to the codec or its surrounding execution flow.
GLOBAL_TEMPLATE = 'c2810f88c1afbec80d328df0134d481d0ecf44f5880ef7d61aa8b3cfe4863b67'
LITERAL = r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
PACKED = re.compile(
    r'eval\((function\(p,a,c,k,e(?:,[dr])?\).*?\})\s*\(\s*(' + LITERAL +
    r')\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(' + LITERAL +
    r")\.split\('\|'\),0,\{\}\)\)", re.S)
GLOBAL_PAYLOAD = re.compile(r'var enkripsi="([A-Za-z0-9+/=]+)"')
ALPHABET = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def js_literal(literal):
    """Parse the supported quoted-string subset; never evaluate an expression."""
    if len(literal) < 2 or literal[0] not in "'\"" or literal[-1] != literal[0]:
        raise ValueError('Invalid quoted literal')
    result, cursor = [], 1
    simple = {'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f', 'v': '\v',
              '\\': '\\', "'": "'", '"': '"', '/': '/'}
    while cursor < len(literal) - 1:
        char = literal[cursor]
        cursor += 1
        if char != '\\':
            if char in '\r\n' or char == literal[0]:
                raise ValueError('Unescaped newline or quote')
            result.append(char)
            continue
        if cursor >= len(literal) - 1:
            raise ValueError('Truncated escape')
        char = literal[cursor]
        cursor += 1
        if char in simple:
            result.append(simple[char])
        elif char in ('x', 'u'):
            length = 2 if char == 'x' else 4
            digits = literal[cursor:cursor + length]
            if len(digits) != length or not re.fullmatch('[0-9a-fA-F]+', digits):
                raise ValueError('Invalid hexadecimal escape')
            result.append(chr(int(digits, 16)))
            cursor += length
        elif char == '\n':
            pass
        elif char == '\r':
            if literal[cursor:cursor + 1] == '\n':
                cursor += 1
        elif char == '0' and not literal[cursor:cursor + 1].isdigit():
            result.append('\0')
        else:
            raise ValueError('Unsupported string escape')
    value = ''.join(result)
    # Preserve paired UTF-16 escapes as Unicode; lone surrogates are unsupported.
    return value.encode('utf-16-le', errors='surrogatepass').decode('utf-16-le')


def unpack(payload, radix, count, dictionary):
    words = dictionary.split('|')
    if not 2 <= radix <= 62 or not 0 <= count <= len(words):
        raise ValueError('Invalid packer radix or dictionary count')

    def replace(match):
        if len(match[0]) > 1 and match[0].startswith('0'):
            return match[0]  # Packer dictionary keys use canonical radix digits.
        value = 0
        for char in match[0]:
            digit = ALPHABET.find(char)
            if not 0 <= digit < radix:
                return match[0]
            value = value * radix + digit
            if value >= count:
                return match[0]
        return words[value] if words[value] else match[0]

    return re.sub(r'\b\w+\b', replace, payload, flags=re.ASCII)


def decode_global_payload(payload):
    encoded = base64.b64decode(payload, validate=True)
    # ArcBase.decode includes a UTF-8 decoder. For this verified ASCII payload
    # it is identity; do not silently apply byte XOR to unknown non-ASCII input.
    if any(value >= 128 for value in encoded):
        raise ValueError('Non-ASCII ArcBase payload is not supported')
    text = ''.join(chr(value ^ 3) for value in encoded)
    text = re.sub(r'%u([0-9a-fA-F]{4})|%([0-9a-fA-F]{2})',
                  lambda match: chr(int(match[1] or match[2], 16)), text)
    # JavaScript substr counts UTF-16 code units, not Unicode code points.
    units = text.encode('utf-16-le', errors='surrogatepass')
    if len(units) < 38:
        raise ValueError('Decoded payload is shorter than the wrapper prefix')
    return 'ArcBase._tt=function()' + units[38:].decode('utf-16-le')


def decode_text(source):
    blocks = []

    def replace(match):
        body_hash = sha256(match[1].encode())
        row = dict(wrapper='Dean Edwards packer', character_offset=match.start(),
                   boilerplate_sha256=body_hash)
        try:
            if body_hash not in PACKERS or int(match[3]) > PACKERS[body_hash]:
                raise ValueError('Unverified packer boilerplate or radix')
            decoded = unpack(js_literal(match[2]), int(match[3]), int(match[4]), js_literal(match[5]))
            row['status'] = 'decoded'
            blocks.append(row)
            return decoded
        except (ValueError, UnicodeError) as error:
            row.update(status='unresolved', reason=str(error))
            blocks.append(row)
            return match[0]

    decoded = PACKED.sub(replace, source)
    global_matches = list(GLOBAL_PAYLOAD.finditer(source))
    inline = None
    if global_matches:
        row = dict(wrapper='base64/XOR3/JS-unescape/substr19', status='unresolved')
        template = GLOBAL_PAYLOAD.sub('var enkripsi="<payload>"', source)
        try:
            if len(global_matches) != 1 or sha256(template.encode()) != GLOBAL_TEMPLATE:
                raise ValueError('Unverified global.js template')
            inline = decode_global_payload(global_matches[0][1])
            row['status'] = 'decoded'
        except (ValueError, UnicodeError) as error:
            row['reason'] = str(error)
        blocks.append(row)
    return decoded, inline, blocks


def run(root, output):
    root = root.resolve(strict=True)
    output = output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError('Use a new output directory outside the input tree')
    if any((parent / '.git').exists() for parent in (output, *output.parents)):
        raise ValueError('Output must be outside Git')
    os.umask(0o077)
    output.mkdir(parents=True, mode=0o700)
    rows, scanned = [], 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ('.js', '.htm', '.html'):
            continue
        scanned += 1
        data = path.read_bytes()
        try:
            source = data.decode('utf-8')
        except UnicodeError:
            rows.append(dict(path=str(path.relative_to(root)), status='unresolved_encoding', input_sha256=sha256(data)))
            continue
        decoded, inline, blocks = decode_text(source)
        candidate = bool(re.search(r'eval\s*\(|var\s+enkripsi\s*=', source))
        if not blocks and not candidate:
            continue
        relative = path.relative_to(root)
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(decoded.encode())
        row = dict(path=str(relative), input_sha256=sha256(data), blocks=blocks,
                   decoded_blocks=sum(block['status'] == 'decoded' for block in blocks),
                   output_path=str(relative), output_sha256=sha256(decoded.encode()),
                   remaining_eval_candidates=len(re.findall(r'eval\s*\(', decoded)))
        if inline is not None:
            inline_path = relative.with_name(relative.name + '.decoded-inline.js')
            (output / inline_path).write_bytes(inline.encode())
            row.update(inline_path=str(inline_path), inline_sha256=sha256(inline.encode()))
        row['status'] = 'decoded' if row['decoded_blocks'] else 'unresolved_candidate'
        if any(block['status'] != 'decoded' for block in blocks):
            row['status'] = 'partial' if row['decoded_blocks'] else 'unresolved_candidate'
        rows.append(row)
    manifest = dict(scanned_text_files=scanned, files=rows,
                    decoded_files=sum(row.get('decoded_blocks', 0) > 0 for row in rows),
                    decoded_blocks=sum(row.get('decoded_blocks', 0) for row in rows),
                    target_javascript_executed=False,
                    all_javascript_semantics_proven=False)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = run(args.root, args.output)
    print(json.dumps({key: result[key] for key in ('scanned_text_files', 'decoded_files', 'decoded_blocks')}))


if __name__ == '__main__':
    main()
