"""Run and compare complete development cohorts without using the held-out suite."""
from collections import Counter
import json
import math
from pathlib import Path
import re
from statistics import median

from dev import broad_runner, fast12, v1_pilot_report
from lilguy.loop import policy_of


def parse_models(specs, reference):
    models = {}
    for spec in specs:
        label, sep, location = spec.partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', label):
            raise ValueError('each --model needs a label and path in LABEL=/path/to/model.gguf form')
        if label in models:
            raise ValueError(f'duplicate model label: {label}')
        path = Path(location).resolve()
        if not location or not path.is_file():
            raise ValueError(f'missing local GGUF for {label}: {location}')
        models[label] = path
    if len(models) < 2 or reference not in models:
        raise ValueError('screen requires two or more --model entries and a --reference matching one label')
    return models


def summarize(directory, suite, tasks):
    identity, passed = v1_pilot_report.read_suite(directory, suite, tasks.keys())
    for key in ('evaluation_sha256', 'gguf_sha256'):
        if not re.fullmatch('[a-f0-9]{64}', identity[key]):
            raise ValueError(f'invalid {key}: {directory}')
    rows = json.loads((directory / f'{suite}.json').read_text())['tasks']
    terminals, timings = Counter(), {'episode_seconds': [], 'model_seconds': []}
    policy_stops = done_misses = 0
    for row in rows:
        case = json.loads((directory / f"task_{row['task']}.json").read_text())
        model = case['model']
        if (case['task'] != row['task'] or case['infra_failure'] is not False or model['infra_error'] is not None
                or model['terminal'] != row['terminal'] or model['metrics'] != row['metrics']):
            raise ValueError(f"inconsistent trace: {directory}/{row['task']}")
        terminals[model['terminal']] += 1
        done_misses += model['terminal'] == 'done' and not row['passed']
        policy_stops += sum(policy_of(e['observation']) in ('pending', 'rejected') for e in model['events'])
        for key, values in timings.items():
            value = row['metrics'][key]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f'invalid {key}: {directory}')
            values.append(value)
    # All suites carry a calibrated scripted terminal even when the expected grader is private.
    clarifications = {key for key, task in tasks.items() if task.oracle[-1].splitlines()[0] == 'ask'}
    return identity, dict(directory=str(directory), completed=len(passed), total=len(tasks),
                          passed_tasks=sorted(passed), terminals=dict(terminals), done_misses=done_misses,
                          policy_stops=policy_stops, originals_preserved=len(tasks), infra_failures=0,
                          clarification_total=len(clarifications), correct_clarifications=sorted(passed & clarifications),
                          median_episode_seconds=median(timings['episode_seconds']),
                          median_model_seconds=median(timings['model_seconds']))


def run(directory, models, reference, device, gate, evaluate):
    suites = {'fast12': {t.id: t for t in fast12.TASKS},
              'broad': {t.id: t for t, _ in broad_runner.task_graders()}}
    identities, results = {}, {}
    (directory / 'plan.json').write_text(json.dumps(dict(models={k: str(p) for k, p in models.items()},
        suites={k: list(v) for k, v in suites.items()}, device=device, reference=reference,
        split_gate=gate), indent=2) + '\n')
    for label, model in models.items():
        results[label] = dict(suites={})
        for suite, tasks in suites.items():
            out = directory / label / suite
            out.mkdir(parents=True)
            print(f'{label}: {suite}', flush=True)
            rc = evaluate(out, suite, model)
            identity, summary = summarize(out, suite, tasks)
            job = json.loads((out / 'result.json').read_text())
            expected_exit = int(summary['completed'] != summary['total'])
            if rc != expected_exit or [stage['exit'] for stage in job['stages']] != [expected_exit]:
                raise ValueError(f'unexpected evaluation process status: {out}')
            if identity['device'] != device:
                raise ValueError(f'device changed during screen: {out}')
            fingerprint = identity['evaluation_sha256']
            if identities.setdefault(suite, fingerprint) != fingerprint:
                raise ValueError(f'{suite} evaluation fingerprint changed during screen: {out}')
            artifact = identity['gguf_sha256']
            if results[label].setdefault('gguf_sha256', artifact) != artifact:
                raise ValueError(f'{label} artifact changed between suites: {out}')
            results[label]['suites'][suite] = summary
        results[label]['completed'] = sum(s['completed'] for s in results[label]['suites'].values())
    for row in results.values():
        for suite, summary in row['suites'].items():
            baseline = results[reference]['suites'][suite]
            a, b = set(summary['passed_tasks']), set(baseline['passed_tasks'])
            summary['only_model'] = sorted(a - b)
            summary['only_reference'] = sorted(b - a)
            ref_time = baseline['median_episode_seconds']
            summary['episode_ratio_to_reference'] = summary['median_episode_seconds'] / ref_time if ref_time else None
    result = dict(reference=reference, device=device, evaluation_sha256=identities, models=results,
                  tasks_per_model=sum(map(len, suites.values())))
    (directory / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
