"""Classify development failures of a pilot job by roadmap category and failure mode.

Reads only development task traces (Fast12 and broad) written by the factory; never the held-out
suite. Usage: python -m dev.v2_failures PILOT_DIR [--side tuned]
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from dev import dev_categories
from dev.v2_report import SUITES
from lilguy.loop import policy_of


def mode(task, verdict):
    model = verdict['model']
    expected = task.oracle[-1].split('\n', 1)[0]
    terminal = model['terminal']
    events = model['events']
    reasons = ' '.join(model['failures'] or [])
    policies = [policy_of(e['observation']) for e in events]
    if terminal == 'invalid':
        return 'invalid-action'
    if terminal == 'budget':
        return 'budget-exhausted'
    if expected == 'ask' and terminal != 'ask':
        return 'should-ask-but-acted'
    if expected != 'ask' and terminal == 'ask':
        return 'asked-unnecessarily'
    if 'pending' in policies and terminal == 'done' and 'pending' not in (model['answer'] or '').lower():
        return 'pending-claimed-done'
    if events and events[-1]['is_error'] and terminal == 'done' and policies[-1] == 'ok':
        return 'done-right-after-error'
    if 'changes mismatch' in reasons or 'changes' in reasons and 'expected' in reasons:
        return 'wrong-effect' if model['changes'] else 'no-effect'
    if any(not e['is_error'] for e in events) and not model['changes'] and 'answer' in reasons:
        return 'wrong-or-missing-answer'
    return 'other: ' + reasons[:80]


def classify(directory, base, side):
    rows = []
    for suite, tasks in SUITES.items():
        folder = Path(directory) / base / side / suite
        for task_id, task in tasks.items():
            path = folder / f'task_{task_id}.json'
            if not path.is_file():  # older reports predate later development batches
                continue
            verdict = json.loads(path.read_text())
            if verdict['passed']:
                continue
            rows.append({'task': task_id, 'suite': suite, 'category': dev_categories.category(task_id),
                         'mode': mode(task, verdict), 'terminal': verdict['model']['terminal'],
                         'actions': [e['action']['kind'] + (' ' + e['action']['tool'] if e['action']['tool'] else '')
                                     for e in verdict['model']['events']],
                         'reasons': (verdict['model']['failures'] or [])[:2]})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('directory', type=Path)
    parser.add_argument('--side', default='tuned', choices=('stock', 'tuned'))
    args = parser.parse_args(argv)
    bases = [p.name for p in sorted(args.directory.iterdir()) if (p / args.side).is_dir()]
    report = {}
    for base in bases:
        rows = classify(args.directory, base, args.side)
        by_mode = Counter(r['mode'] for r in rows)
        by_cat = defaultdict(Counter)
        for r in rows:
            by_cat[r['category']][r['mode']] += 1
        report[base] = {'failures': len(rows), 'by_mode': dict(by_mode.most_common()),
                        'by_category': {c: dict(m) for c, m in sorted(by_cat.items())}, 'tasks': rows}
    out = args.directory / f'failures-{args.side}.json'
    out.write_text(json.dumps(report, indent=2) + '\n')
    for base, r in report.items():
        print(base, r['failures'], json.dumps(r['by_mode']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
