#!/usr/bin/env python3
"""Batch static ELF export with a content-addressed private evidence ledger.

One Ghidra process per shard amortizes startup. Never executes target binaries.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

ARTIFACTS = ('summary.json', 'functions.jsonl', 'pseudocode.c', 'assembly.txt')
SCRIPTS = Path(__file__).resolve().parent


def private_directory(path):
    path = path.resolve()
    if any((p / '.git').exists() for p in (path, *path.parents)):
        raise ValueError('Evidence output must be outside Git')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def checkpoint(output, rows, processes):
    states = []
    finished = bool(processes) and all(p.poll() is not None for p in processes)
    for row in rows:
        state = dict(row)
        summary = output / 'modules' / row['sha256'] / 'summary.json'
        if summary.exists():
            try:
                data = json.loads(summary.read_text())
            except (ValueError, OSError):
                state['status'] = 'invalid_summary' if finished else 'pending_or_running'
                states.append(state)
                continue
            state['summary'] = data
            counts = [data.get(key) for key in ('recognized_functions', 'decompiled_functions', 'failed_functions')]
            if data.get('input_sha256', '').lower() != row['sha256']:
                state['status'] = 'digest_mismatch'
            elif (any(type(value) is not int or value < 0 for value in counts)
                  or counts[0] != counts[1] + counts[2]):
                state['status'] = 'invalid_counts'
            elif not all((summary.parent / name).is_file() for name in ARTIFACTS):
                state['status'] = 'missing_artifacts'
            elif data.get('analysis_timed_out') or data.get('failed_functions') or not data.get('recognized_functions'):
                state['status'] = 'partial'
            else:
                state['status'] = 'exported'
        else:
            state['status'] = 'missing_export' if finished else 'pending_or_running'
        states.append(state)
    result = dict(modules=states, processes=[dict(shard=i, pid=p.pid, exit_code=p.poll())
                                            for i, p in enumerate(processes)],
                  all_machine_code_proven_covered=False)
    temp = output / 'coverage.json.tmp'
    temp.write_text(json.dumps(result, indent=2))
    temp.replace(output / 'coverage.json')
    return result


def run(roots, output, ghidra, reuse, workers, analysis_timeout):
    os.umask(0o077)
    roots = [p.resolve(strict=True) for p in roots]
    output = output.resolve()
    if any(output.is_relative_to(root) for root in roots):
        raise ValueError('Output must be outside input trees')
    if output.exists():
        raise ValueError('Use a new batch directory; existing output is never overwritten')
    output = private_directory(output)
    headless = ghidra.resolve(strict=True) / 'support/analyzeHeadless'
    if not headless.is_file():
        raise ValueError('Missing analyzeHeadless')
    modules = output / 'modules'
    modules.mkdir()
    rows = {}
    for number, root in enumerate(roots):
        for path in sorted(root.rglob('*')):
            if path.is_symlink() or not path.is_file():
                continue
            with path.open('rb') as stream:
                if stream.read(4) != b'\x7fELF':
                    continue
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            row = rows.setdefault(digest, dict(sha256=digest, bytes=len(data), paths=[], source=str(path)))
            row['paths'].append(dict(root=number, path=str(path.relative_to(root))))
    if not rows:
        raise ValueError('No ELF inputs')
    # Reuse only complete prior exports with matching input digests.
    if reuse:
        for summary in reuse.resolve(strict=True).glob('*/summary.json'):
            data = json.loads(summary.read_text())
            digest = data.get('input_sha256', '').lower()
            if digest not in rows or data.get('failed_functions') or not data.get('recognized_functions'):
                continue
            log = summary.parent / 'headless.log'
            if data.get('analysis_timed_out') or not log.exists() or 'Analysis timed out' in log.read_text(errors='replace'):
                continue
            if not all((summary.parent / name).is_file() for name in ARTIFACTS):
                continue
            dest = modules / digest
            dest.mkdir(exist_ok=True)
            for name in (*ARTIFACTS, 'headless.log'):
                shutil.copy2(summary.parent / name, dest / name)
            rows[digest]['reused_from'] = str(summary.parent)
    inventory = dict(roots=[str(p) for p in roots], modules=list(rows.values()))
    (output / 'inventory.json').write_text(json.dumps(inventory, indent=2))
    stages = [output / f'stage-{i}' for i in range(workers)]
    for stage in stages:
        stage.mkdir()
    sizes = [0] * workers
    for row in sorted(rows.values(), key=lambda r: r['bytes'], reverse=True):
        if 'reused_from' in row:
            continue
        shard = min(range(workers), key=lambda i: sizes[i])
        sizes[shard] += row['bytes']
        shutil.copyfile(row['source'], stages[shard] / (row['sha256'] + '.elf'))
    project = output / 'projects'
    project.mkdir()
    processes, logs = [], []
    try:
        for i, stage in enumerate(stages):
            if not any(stage.iterdir()):
                continue
            log = (output / f'headless-{i}.log').open('w')
            logs.append(log)
            args = [str(headless), str(project), f'batch_{i}', '-import', str(stage), '-recursive',
                    '-analysisTimeoutPerFile', str(analysis_timeout), '-max-cpu', '2',
                    '-scriptPath', str(SCRIPTS), '-postScript', 'ExportFirmwareCode.java',
                    str(modules), '--per-program']
            processes.append(subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log,
                                               stderr=subprocess.STDOUT, start_new_session=True))
        while any(p.poll() is None for p in processes):
            checkpoint(output, list(rows.values()), processes)
            time.sleep(5)
        result = checkpoint(output, list(rows.values()), processes)
        (output / 'completed.json').write_text(json.dumps(result, indent=2))
    finally:
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        for log in logs:
            log.close()
    return 0 if all(r['status'] == 'exported' for r in result['modules']) and all(p.returncode == 0 for p in processes) else 1


def main():
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ghidra', type=Path, required=True)
    parser.add_argument('--reuse', type=Path)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--analysis-timeout', type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.analysis_timeout <= 3600:
        parser.error('analysis timeout must be 1..3600 seconds')
    return run(args.root, args.output, args.ghidra, args.reuse, args.workers, args.analysis_timeout)


if __name__ == '__main__':
    raise SystemExit(main())
