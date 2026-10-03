"""Portable exact-integer FPGA evidence checks. Python 3.10+, standard library only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integer_result(value):
    # Deliberately reject floats and booleans: Python considers 1 == True == 1.0.
    if type(value) is int or value is None:
        return True
    if isinstance(value, list):
        return all(integer_result(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and integer_result(v) for k, v in value.items())
    return False


def records(path):
    result = {}
    for line_no, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        key = row.get('case_id')
        require(isinstance(key, str) and key, f'line {line_no}: invalid case_id')
        require(key not in result, f'duplicate case_id: {key}')
        require(re.fullmatch(r'[0-9a-f]{64}', row.get('input_sha256', '')) is not None,
                f'{key}: input_sha256 must be lowercase SHA256')
        require('result' in row and integer_result(row['result']), f'{key}: result must contain exact integers/null')
        result[key] = row
    require(result, 'empty record set')
    return result


def compare(expected_path, observed_path, build_id):
    expected, observed = records(expected_path), records(observed_path)
    require(expected.keys() == observed.keys(),
            f'case set mismatch: missing={sorted(expected.keys()-observed.keys())}, extra={sorted(observed.keys()-expected.keys())}')
    for key, gold in expected.items():
        row = observed[key]
        require(row.get('build_id') == build_id, f'{key}: build_id mismatch')
        require(row['input_sha256'] == gold['input_sha256'], f'{key}: input mismatch')
        require(row['result'] == gold['result'], f'{key}: result mismatch')
    return dict(status='PASS', check='exact_integer_results', cases=len(expected), build_id=build_id)


def files(root, manifest_path):
    root = Path(root).resolve()
    hashes = read(manifest_path)['sha256']
    require(isinstance(hashes, dict) and hashes, 'empty hash manifest')
    names = set()
    for name, digest in hashes.items():
        require(isinstance(name, str) and re.fullmatch(r'[a-z0-9_.\-/]+', name), 'unsafe filename')
        require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'unsafe relative path')
        require(name.casefold() not in names, 'case-insensitive duplicate path')
        names.add(name.casefold())
        path = (root / name).resolve()
        require(path.is_relative_to(root), f'path escapes root: {name}')
        require(path.is_file(), f'missing artifact: {name}')
        require(sha(path) == digest, f'hash mismatch: {name}')
    return dict(status='PASS', check='artifact_hashes', files=len(hashes))


def timing(path):
    data = read(path)
    rows = data['trials']
    require(rows, 'empty timing set')
    fields = ['task', 'case_id', 'input_sha256', 'build_id', 'clock_hz', 'boundary']
    base = rows[0]
    require(base.get('boundary') == 'board_full_task', 'timing boundary must be board_full_task')
    require(type(base.get('clock_hz')) is int and base['clock_hz'] > 0, 'invalid clock_hz')
    require(all(base.get(k) for k in fields), 'missing timing identity field')
    require(re.fullmatch(r'[0-9a-f]{64}', base['input_sha256']) is not None, 'invalid timing input hash')
    grouped = {'cpu': [], 'accelerator': []}
    for row in rows:
        require(all(row.get(k) == base[k] for k in fields), 'unfair timing: different task/input/build/clock/boundary')
        require(row.get('mode') in grouped, 'timing mode must be cpu or accelerator')
        require(type(row.get('cycles')) is int and row['cycles'] > 0, 'cycles must be positive integers')
        grouped[row['mode']].append(row['cycles'])
    require(all(grouped.values()), 'both cpu and accelerator trials required')
    require(len(grouped['cpu']) == len(grouped['accelerator']), 'unequal trial counts')
    med = {k: statistics.median(v) for k, v in grouped.items()}
    return dict(status='PASS', check='same_task_timing', identity={k:base[k] for k in fields},
                repeats_per_mode=len(grouped['cpu']), median_cycles=med,
                median_ms={k:v * 1000 / base['clock_hz'] for k,v in med.items()},
                speedup=med['cpu']/med['accelerator'],
                excludes='UART, host rendering and post-timing verification; inspect instrumentation separately')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('compare')
    p.add_argument('expected'); p.add_argument('observed'); p.add_argument('--build-id', required=True)
    p = sub.add_parser('files')
    p.add_argument('root'); p.add_argument('manifest')
    p = sub.add_parser('timing'); p.add_argument('records')
    args = parser.parse_args()
    try:
        if args.action == 'compare': result = compare(args.expected, args.observed, args.build_id)
        elif args.action == 'files': result = files(args.root, args.manifest)
        else: result = timing(args.records)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps(dict(status='FAIL', error=str(error)), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
