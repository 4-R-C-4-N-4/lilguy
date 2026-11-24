"""Evaluate the non-Fast12 development fixtures through the shared guarded runner."""
import argparse
import json
from pathlib import Path
import tempfile

from dev import (broad_dev, dev_archives, dev_decisions, dev_organise, dev_recovery, dev_shell, dev_text_workflows,
                 dev_verification, dev_workspace, fast12, fast12_runner)
from lilguy import protocol

SUITES = (broad_dev, dev_shell, dev_decisions, dev_verification, dev_workspace, dev_text_workflows,
          dev_archives, dev_organise, dev_recovery)
SOURCES = ('dev/broad_runner.py', *(f'{suite.__name__.replace(".", "/")}.py' for suite in SUITES))


def task_graders():
    for suite in SUITES:
        for task in suite.TASKS:
            yield task, suite.grade


def development_rows():
    tasks = (*fast12.TASKS, *(task for task, _ in task_graders()))
    return [dict(id=t.id, split='dev', template_id=t.id, request=t.request, files=t.files) for t in tasks]


def write_summary(out, verdicts):
    tasks = []
    for verdict in verdicts:
        model = verdict['model']
        tasks.append({
            'task': verdict['task'], 'passed': verdict['passed'] and model['original_unchanged'] is True,
            'infra_failure': verdict['infra_failure'], 'original_unchanged': model['original_unchanged'],
            'terminal': model['terminal'], 'metrics': model.get('metrics'),
        })
    summary = {
        'total': len(tasks), 'passed': sum(t['passed'] for t in tasks),
        'infra_failures': sum(t['infra_failure'] for t in tasks),
        'originals_changed': sum(t['original_unchanged'] is False for t in tasks), 'tasks': tasks,
    }
    (out / 'broad.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if tasks and summary['passed'] == len(tasks) and not summary['infra_failures'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server')
    parser.add_argument('gguf')
    parser.add_argument('out', type=Path)
    parser.add_argument('--interface', type=int, default=protocol.INTERFACE_VERSION,
                        choices=protocol.SUPPORTED_VERSIONS)
    args = parser.parse_args(argv)
    tools = protocol.load_tools()
    verdicts = []
    with fast12_runner.managed_server(args.server, args.gguf, args.out) as (port, opener):
        for task, grade in task_graders():
            with tempfile.TemporaryDirectory() as tmp:
                verdict = fast12_runner.judge_task(Path(tmp), task, tools, port, opener, grade, args.interface)
            verdicts.append(verdict)
            (args.out / f'task_{task.id}.json').write_text(json.dumps(verdict, indent=2) + '\n')
    return write_summary(args.out, verdicts)


if __name__ == '__main__':
    raise SystemExit(main())
