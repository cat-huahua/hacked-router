#!/usr/bin/env python3
"""Independently reconcile exported function records with per-program summaries."""
import argparse
import hashlib
import json
from pathlib import Path


def audit(directory):
    rows = []
    for summary_file in sorted(directory.rglob('summary.json')):
        if not (summary_file.parent / 'functions.jsonl').exists():
            continue
        errors = []
        summary = json.loads(summary_file.read_text())
        index = summary_file.parent / 'functions.jsonl'
        records = []
        for ordinal, line in enumerate(index.read_text().splitlines(), 1):
            try:
                row = json.loads(line)
                if not isinstance(row.get('decompiled'), bool):
                    errors.append(f'invalid status at record {ordinal}')
                records.append(row)
            except ValueError:
                errors.append(f'invalid JSON at record {ordinal}')
        successful = sum(r.get('decompiled') is True for r in records)
        failed = sum(r.get('decompiled') is False for r in records)
        if len(records) != summary.get('recognized_functions'):
            errors.append('recognized count mismatch')
        if successful != summary.get('decompiled_functions') or failed != summary.get('failed_functions'):
            errors.append('success/failure count mismatch')
        if len({r.get('address') for r in records}) != len(records):
            errors.append('duplicate function address')
        hashes = {}
        for name in ('pseudocode.c', 'assembly.txt', 'functions.jsonl', 'summary.json'):
            path = summary_file.parent / name
            if not path.is_file() or not path.stat().st_size:
                errors.append(f'missing or empty {name}')
            else:
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(dict(directory=str(summary_file.parent.relative_to(directory)),
                         input_sha256=summary.get('input_sha256'), recognized=len(records),
                         decompiled=successful, failed=failed, errors=errors,
                         artifact_sha256=hashes))
    return dict(modules=len(rows), reconciled=sum(not r['errors'] for r in rows), rows=rows,
                all_machine_code_proven_covered=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve(strict=True)
    if any((p / '.git').exists() for p in (directory, *directory.parents)):
        parser.error('Audit output must be outside Git')
    result = audit(directory)
    (directory / 'export-audit.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ('modules', 'reconciled')}))
    raise SystemExit(0 if result['modules'] and result['modules'] == result['reconciled'] else 1)
