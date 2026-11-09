#!/usr/bin/env python3
"""Build a private, linked index of an existing batch export. No target execution."""
import argparse
from collections import Counter
import json
from pathlib import Path


def report(batch):
    batch = batch.resolve(strict=True)
    if any((p / '.git').exists() for p in (batch, *batch.parents)):
        raise ValueError('Report belongs outside Git with the private evidence')
    coverage = json.loads((batch / 'coverage.json').read_text())
    rows = coverage['modules']
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
        count = f"{summary.get('decompiled_functions', '—')} / {summary.get('failed_functions', '—')}"
        lines.append(f"| {label} | {row['status']} | {count} | {links} |")
    lines.extend(['', '## 其他层', '',
                  '- 原始 rootfs 的 shell/HTML/JavaScript 等文本可以直接阅读，无需反编译。',
                  '- EmbedUR 解码证据：上级目录的 `embedur-decode-summary.json`、`embedur-archive-members.json`。',
                  '- Web wrapper 解码：上级目录的 `web-decoded/manifest.json`。',
                  '- kernel：上级目录的 `kernel/summary.json` 为符号统计，`kernel/decompiled/summary.json` 才是函数导出统计。',
                  '- bootloader 不在这份输入材料中；外部加密容器、设备当前 flash 配置不在本索引覆盖范围内。', ''])
    destination = batch / 'INDEX.md'
    destination.write_text('\n'.join(lines))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    args = parser.parse_args()
    print(report(args.batch))
