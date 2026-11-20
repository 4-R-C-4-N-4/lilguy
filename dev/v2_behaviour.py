"""Behaviour checks for interface-v2 development traces (development suites only, never held-out).

For one scored side (`<job>/<base>/<side>` with fast12/ and broad/ task traces) it reports:

* answer omissions: tasks whose scripted oracle staged nothing and stayed `policy: ok` (an answer
  is the deliverable) where the model ended with a bare `done`;
* input edits: staged changes to files that existed in the fixture and that the oracle leaves
  alone, flagged separately when the request says not to modify anything;
* unexpected policy stops: pending/rejected observations in tasks whose oracle had none;
* answered misses: failed answer tasks where the model did answer (candidates for a confirmed
  wrong answer; confirm by reading the trace).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from dev import broad_runner, fast12
from lilguy.loop import policy_of

READ_ONLY_REQUEST = re.compile(
    r"do not (?:modify|change|edit|create|write)|don't (?:modify|change|edit)|leave (?:both|it|them|the file|\w+)"
    r"[^.]{0,30}(?:alone|unchanged|as (?:it is|they are))|without (?:editing|writing|changing)|only (?:check|look)",
    re.IGNORECASE)


def _files():
    return {t.id: t for t in (*fast12.TASKS, *(t for t, _ in broad_runner.task_graders()))}


def traces(side):
    for suite in ('fast12', 'broad'):
        for path in sorted((Path(side) / suite).glob('task_*.json')):
            yield json.loads(path.read_text())


def answer_required(oracle):
    return not oracle['changes'] and all(policy_of(e['observation']) == 'ok' for e in oracle['events'])


def check(side):
    tasks = _files()
    rows = {'answer_omissions': [], 'input_edits': [], 'do_not_modify_edits': [], 'unexpected_policy_stops': [],
            'answered_misses': []}
    for verdict in traces(side):
        task = tasks[verdict['task']]
        model, oracle = verdict['model'], verdict['oracle']
        needs_answer = answer_required(oracle)
        if needs_answer and model['terminal'] == 'done' and not (model['answer'] or '').strip():
            rows['answer_omissions'].append(task.id)
        if needs_answer and not verdict['passed'] and (model['answer'] or '').strip():
            rows['answered_misses'].append({'task': task.id, 'answer': model['answer']})
        edited = sorted(p for p in model['changes'] if p in task.files and p not in oracle['changes'])
        if edited:
            rows['input_edits'].append({'task': task.id, 'paths': edited})
            if READ_ONLY_REQUEST.search(task.request):
                rows['do_not_modify_edits'].append({'task': task.id, 'paths': edited})
        oracle_stops = {policy_of(e['observation']) for e in oracle['events']} - {'ok'}
        for event in model['events']:
            policy = policy_of(event['observation'])
            if policy in ('pending', 'rejected') and policy not in oracle_stops:
                rows['unexpected_policy_stops'].append({'task': task.id, 'policy': policy})
    rows['counts'] = {key: len(value) for key, value in rows.items()}
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('side', nargs='+', type=Path)
    args = parser.parse_args(argv)
    print(json.dumps({str(side): check(side) for side in args.side}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
