"""Compare completed stock and tuned pilot evaluations, refusing incomplete evidence."""
import argparse
import json
from pathlib import Path

from dev import broad_runner, fast12


def read_suite(path, suite, expected):
    identity = json.loads((path / 'identity.json').read_text())
    report = json.loads((path / f'{suite}.json').read_text())
    rows = report['tasks']
    if (report['infra_failures'] or len(rows) != len(expected) or report['total'] != len(expected)
            or {row['task'] for row in rows} != expected or any(row['infra_failure'] for row in rows)
            or report['passed'] != sum(row['passed'] for row in rows)):
        raise ValueError(f'incomplete or failed evaluation evidence: {path}')
    for row in rows:
        trace = json.loads((path / f"task_{row['task']}.json").read_text())
        if (trace['model']['original_unchanged'] is not True or not trace['controls_agree']
                or trace['passed'] is not row['passed']):
            raise ValueError(f"inconsistent or unsafe trace: {path}/{row['task']}")
    return identity, {row['task'] for row in rows if row['passed']}


def compare(manifest):
    expected = {'fast12': {task.id for task in fast12.TASKS},
                'broad': {task.id for task, _ in broad_runner.task_graders()}}
    keys = {(side, suite) for side in ('stock', 'tuned') for suite in expected}
    rows = {}
    for line in manifest.read_text().splitlines():
        side, suite, path, _ = line.split('\t')
        key = side, suite
        if key not in keys or key in rows:
            raise ValueError(f'unexpected or duplicate pilot report row: {key}')
        rows[key] = read_suite(Path(path), suite, expected[suite])
    if rows.keys() != keys:
        raise ValueError('pilot comparison is missing an evaluation')
    for side in ('stock', 'tuned'):
        identity = rows[(side, 'fast12')][0]
        other = rows[(side, 'broad')][0]
        if any(identity[k] != other[k] for k in ('device', 'gguf_sha256')):
            raise ValueError(f'{side} artifact or device changed between suites')
    result = {}
    for suite in expected:
        stock, passed = rows[('stock', suite)]
        tuned, new_passed = rows[('tuned', suite)]
        if any(stock[k] != tuned[k] for k in ('evaluation_sha256', 'device')):
            raise ValueError(f'{suite} evaluation identity changed')
        result[suite] = dict(total=len(expected[suite]), stock_passed=len(passed), tuned_passed=len(new_passed),
                             improved=sorted(new_passed - passed), regressed=sorted(passed - new_passed))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.manifest), sort_keys=True))


if __name__ == '__main__':
    main()
