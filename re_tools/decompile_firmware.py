#!/usr/bin/env python3
"""Export Ghidra pseudocode/assembly from an extracted rootfs into private storage.

No firmware code is executed. Analysis output can contain keys and credentials.
Coverage counts apply only to functions Ghidra recognizes, not all machine code.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

REPO = Path(__file__).resolve().parents[1]


def inside_git(path):
    return any((parent / '.git').exists() for parent in (path, *path.parents))


def export(rootfs, output, ghidra, modules, workers=1, analysis_timeout=180):
    rootfs = Path(rootfs).resolve(strict=True)
    output = Path(output).resolve()
    if inside_git(output) or output.is_relative_to(rootfs):
        raise ValueError('output must be outside Git and outside the input rootfs')
    headless = Path(ghidra).resolve(strict=True) / 'support/analyzeHeadless'
    if not headless.is_file():
        raise ValueError('Ghidra support/analyzeHeadless not found')
    os.umask(0o077)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    projects = output / 'projects'
    projects.mkdir(exist_ok=True)
    candidates = []
    if modules:
        for module in modules:
            path = (rootfs / module).resolve(strict=True)
            if not path.is_relative_to(rootfs):
                raise ValueError('module resolves outside rootfs')
            candidates.append(path)
    else:
        candidates = sorted(p for p in rootfs.rglob('*') if not p.is_symlink() and p.is_file())
    rows, seen, jobs = [], {}, []
    for source in candidates:
        with source.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        relative = str(source.relative_to(rootfs))
        if digest in seen:
            rows.append({'path': relative, 'sha256': digest, 'alias_of': seen[digest]})
            continue
        seen[digest] = relative
        case = output / relative.replace('/', '__')
        case.mkdir(exist_ok=True)
        provenance = {'path': relative, 'sha256': digest, 'bytes': source.stat().st_size}
        summary_path = case / 'summary.json'
        if summary_path.exists():
            previous = json.loads(summary_path.read_text())
            artifacts = ('pseudocode.c', 'assembly.txt', 'functions.jsonl')
            if (previous.get('input_sha256', '').lower() == digest
                    and previous.get('failed_functions') == 0
                    and not previous.get('analysis_timed_out', False)
                    and previous.get('recognized_functions', 0) > 0
                    and (case / 'headless.log').is_file()
                    and 'Analysis timed out' not in (case / 'headless.log').read_text(errors='replace')
                    and all((case / name).is_file() for name in artifacts)):
                rows.append({**provenance, 'exit_code': 0, 'reused': True, 'summary': previous})
                continue
        jobs.append((source, case, provenance))

    def analyze(job):
        source, case, provenance = job
        relative, digest = provenance['path'], provenance['sha256']
        # A failed rerun must never inherit a successful old summary.
        (case / 'summary.json').unlink(missing_ok=True)
        (case / 'input.json').write_text(json.dumps(provenance, indent=2))
        project = 'case_' + digest[:20]
        args = [str(headless), str(projects), project, '-import', str(source),
                '-overwrite', '-analysisTimeoutPerFile', str(analysis_timeout), '-max-cpu', '2',
                '-scriptPath', str(REPO / 're_tools'), '-postScript',
                'ExportFirmwareCode.java', str(case)]
        print('Analyzing', relative, flush=True)
        start = time.monotonic()
        with (case / 'headless.log').open('w') as log:
            process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                status = process.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                status = 124
        row = {**provenance, 'exit_code': status, 'seconds': round(time.monotonic() - start, 1)}
        summary = case / 'summary.json'
        if summary.exists():
            row['summary'] = json.loads(summary.read_text())
            row['summary']['analysis_timed_out'] = (
                row['summary'].get('analysis_timed_out', False)
                or 'Analysis timed out' in (case / 'headless.log').read_text(errors='replace'))
            if row['summary'].get('input_sha256', '').lower() != digest:
                row['error'] = 'analysis input digest mismatch'
                row['exit_code'] = 1
        print('Finished', relative, 'exit', status,
              'functions', row.get('summary', {}).get('recognized_functions', 'unknown'), flush=True)
        return row

    def checkpoint():
        temp = output / 'coverage.json.tmp'
        temp.write_text(json.dumps(sorted(rows, key=lambda row: row['path']), indent=2))
        temp.replace(output / 'coverage.json')

    checkpoint()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(analyze, job) for job in jobs]):
            rows.append(future.result())
            checkpoint()
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rootfs')
    parser.add_argument('output')
    parser.add_argument('--ghidra', required=True, help='existing extracted Ghidra distribution')
    parser.add_argument('--module', action='append', default=[], help='relative ELF path; repeat; default all ELF files')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1,
                        help='parallel headless processes; each uses at most two CPUs')
    parser.add_argument('--analysis-timeout', type=int, default=180,
                        help='seconds of automatic analysis per ELF; export has a separate process limit')
    args = parser.parse_args()
    try:
        if args.analysis_timeout < 1 or args.analysis_timeout > 1200:
            raise ValueError('analysis timeout must be between 1 and 1200 seconds')
        rows = export(args.rootfs, args.output, args.ghidra, args.module, args.workers, args.analysis_timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'Export failed: {error}\n')
    failed = not rows or any(row.get('exit_code', 0) != 0 or 'alias_of' not in row and (
        'summary' not in row or row['summary'].get('failed_functions', 0) > 0
        or row['summary'].get('analysis_timed_out', False)
        or row['summary'].get('recognized_functions', 0) == 0) for row in rows)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
