#!/usr/bin/env python3
"""Build a private, linked index of an existing batch export. No target execution."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def verified_retry(module, retry):
    """Reconcile a retry against immutable original evidence before counting it."""
    result = json.loads((retry / 'retry-summary.json').read_text())
    for field, filename in [('source_summary_sha256', 'summary.json'), ('source_index_sha256', 'functions.jsonl')]:
        if result[field] != hashlib.sha256((module / filename).read_bytes()).hexdigest():
            raise ValueError('Retry source evidence hash mismatch')
    base = json.loads((module / 'summary.json').read_text())
    original = [json.loads(s) for s in (module / 'functions.jsonl').read_text().splitlines()]
    records = [json.loads(s) for s in (retry / 'retry-functions.jsonl').read_text().splitlines()]
    expected = {r['address'] for r in original if not r['decompiled']}
    if result['input_sha256'] != base['input_sha256']:
        raise ValueError('Retry input digest mismatch')
    if len(records) != len(expected) or {r['address'] for r in records} != expected:
        raise ValueError('Retry does not cover exactly the original failed entries')
    if any(type(r.get('decompiled')) is not bool for r in records):
        raise ValueError('Invalid retry status')
    succeeded = sum(r['decompiled'] for r in records)
    if (succeeded != result['decompiled_functions'] or len(records) - succeeded != result['failed_functions']
            or len(records) != result['attempted_functions']
            or len(records) != base['failed_functions']
            or not (retry / 'retry-pseudocode.c').is_file()):
        raise ValueError('Retry counters or artifacts disagree')
    return result


def report(batch, retry_root=None):
    batch = batch.resolve(strict=True)
    if any((p / '.git').exists() for p in (batch, *batch.parents)):
        raise ValueError('Report belongs outside Git with the private evidence')
    coverage = json.loads((batch / 'coverage.json').read_text())
    rows = coverage['modules']
    for row in rows:
        row['effective_decompiled_functions'] = row.get('summary', {}).get('decompiled_functions', 0)
        row['effective_failed_functions'] = row.get('summary', {}).get('failed_functions', 0)
        if retry_root is None or not (retry_root / row['sha256'] / 'retry-summary.json').exists():
            continue
        retry = retry_root / row['sha256']
        result = verified_retry(batch / 'modules' / row['sha256'], retry)
        row['retry'] = result
        row['effective_decompiled_functions'] += result['decompiled_functions']
        row['effective_failed_functions'] -= result['decompiled_functions']
        if row['status'] == 'partial' and not row['effective_failed_functions'] and not row['summary'].get('analysis_timed_out'):
            row['status'] = 'exported_with_retry'
    (batch / 'coverage-effective.json').write_text(json.dumps(coverage, indent=2))
    counts = Counter(r['status'] for r in rows)
    lines = ['# WE410443-ST 静态代码导出索引', '',
             '这些文件含原厂固件字符串，可能含凭据。保留在私有目录；pseudocode 不是原始或保证可编译的 C。', '',
             f"不同 ELF：{len(rows)}；路径数：{sum(len(r['paths']) for r in rows)}。", '',
             f'状态：`{dict(counts)}`。', '',
             'exported 表示工具识别出的函数已导出，不证明所有 machine code 被识别或人工验证。', '',
             '| 输入路径 | 状态 | pseudocode 函数 / 失败 | 导出文件 |',
             '|---|---|---:|---|']
    for row in sorted(rows, key=lambda r: (r['paths'][0]['root'], r['paths'][0]['path'])):
        label = '<br>'.join(f"root{p['root']}: `{p['path']}`" for p in row['paths'])
        out = batch / 'modules' / row['sha256']
        links = ' · '.join(f'[{label}]({(out / name).as_posix()})'
                           for label, name in [('C', 'pseudocode.c'), ('ASM', 'assembly.txt'), ('函数索引', 'functions.jsonl')]
                           if (out / name).is_file())
        summary = row.get('summary', {})
        count = f"{row['effective_decompiled_functions']} / {row['effective_failed_functions']}" if summary else '— / —'
        if 'retry' in row:
            links += f" · [重试 C]({retry_root / row['sha256'] / 'retry-pseudocode.c'})"
        lines.append(f"| {label} | {row['status']} | {count} | {links} |")
    lines.extend(['', '## 其他层', '',
                  '- 原始 rootfs 的 shell/HTML/JavaScript 等文本可以直接阅读，无需反编译。',
                  '- EmbedUR 解码证据：上级目录的 `embedur-decode-summary.json`、`embedur-archive-members.json`。',
                  '- Web wrapper 解码：上级目录的 `web-decoded/manifest.json`。',
                  '- kernel：上级目录的 `kernel/summary.json` 为符号统计；若存在 `kernel/refined-decompiled/`，优先阅读其导出及 `export-provenance.json`，初版 `kernel/decompiled/` 仅作历史对照。',
                  '- bootloader 不在这份输入材料中；外部加密容器、设备当前 flash 配置不在本索引覆盖范围内。', ''])
    destination = batch / 'INDEX.md'
    destination.write_text('\n'.join(lines))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--retry', type=Path, help='completed retry output; verifies source hashes before counting recoveries')
    args = parser.parse_args()
    print(report(args.batch, args.retry.resolve(strict=True) if args.retry else None))
