"""Run the v4 focus fixtures (dev/dev_focus.py) on one GGUF, with the usual controls.

    .venv/bin/python -m dev.focus_runner SERVER GGUF OUT [--set v4|r11] [--interface 3]

Development only: separate from the 80-task roster so that roster's fingerprint is unchanged.
Writes task_<id>.json per task and focus.json with per-group counts.
"""
import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path

import importlib

from dev import dev_focus, fast12_runner
from lilguy import protocol


SETS = {'v4': 'dev.dev_focus', 'r11': 'dev.focus_r11', 'append': 'dev.focus_append'}


def group_of(task_id, focus=dev_focus):
    return next(name for name, tasks in focus.GROUPS.items() if any(t.id == task_id for t in tasks))


def summarize(verdicts, focus=dev_focus):
    passed = Counter(group_of(v['task'], focus) for v in verdicts if v['passed'])
    total = Counter(group_of(v['task'], focus) for v in verdicts)
    return {
        'total': len(verdicts), 'passed': sum(1 for v in verdicts if v['passed']),
        'infra_failures': sum(1 for v in verdicts if v['infra_failure']),
        'groups': {name: {'passed': passed[name], 'total': total[name]} for name in focus.GROUPS},
        'tasks': [{'task': v['task'], 'passed': v['passed'], 'infra_failure': v['infra_failure'],
                   'terminal': v['model'].get('terminal'), 'failures': v['model'].get('failures')}
                  for v in verdicts],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server')
    parser.add_argument('gguf')
    parser.add_argument('out', type=Path)
    parser.add_argument('--interface', type=int, default=protocol.INTERFACE_VERSION,
                        choices=protocol.SUPPORTED_VERSIONS)
    parser.add_argument('--set', choices=tuple(SETS), default='v4', help='which focus fixtures')
    args = parser.parse_args(argv)
    focus = importlib.import_module(SETS[args.set])
    args.out.mkdir(parents=True, exist_ok=True)
    tools = protocol.load_tools(version=args.interface)
    verdicts = []
    with fast12_runner.managed_server(args.server, args.gguf, args.out) as (port, opener):
        for task in focus.TASKS:
            with tempfile.TemporaryDirectory() as tmp:
                verdict = fast12_runner.judge_task(Path(tmp), task, tools, port, opener, focus.grade,
                                                   args.interface, ask_ids=focus.ASK, oracles=focus.ORACLES)
            verdicts.append(verdict)
            (args.out / f'task_{task.id}.json').write_text(json.dumps(verdict, indent=2) + '\n')
    summary = {'set': args.set, 'interface': args.interface, **summarize(verdicts, focus)}
    (args.out / 'focus.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'tasks'}, indent=2))
    return 0 if summary['infra_failures'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
