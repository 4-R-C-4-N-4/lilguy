"""Compare completed daily-development reports, never held-out evaluations."""
import json
import re

from dev.fast12 import TASKS


def _load(root):
    identity = json.loads((root / 'identity.json').read_text())
    summary = json.loads((root / 'fast12.json').read_text())
    for key in ('evaluation_sha256', 'gguf_sha256'):
        if not re.fullmatch('[a-f0-9]{64}', identity[key]):
            raise ValueError('invalid run fingerprint')
    scores = {}
    for row in summary['tasks']:
        task = row['task']
        if (task in scores or row['infra_failure'] is not False or type(row['passed']) is not bool
                or row['model_miss'] is not (not row['passed'])):
            raise ValueError('duplicate task, infrastructure failure, or inconsistent verdict')
        scores[task] = row['passed']
    if set(scores) != {task.id for task in TASKS}:
        raise ValueError('incomplete or unexpected task set')
    if [summary[k] for k in ('total', 'passed', 'infra_failures', 'model_misses')] != [
            len(scores), sum(scores.values()), 0, len(scores) - sum(scores.values())]:
        raise ValueError('inconsistent aggregate')
    return identity, scores


def compare(stock, candidate):
    a, old = _load(stock)
    b, new = _load(candidate)
    if a['evaluation_sha256'] != b['evaluation_sha256']:
        raise ValueError('evaluation fingerprints differ; rerun stock')
    return dict(evaluation_sha256=a['evaluation_sha256'], stock_sha256=a['gguf_sha256'],
                candidate_sha256=b['gguf_sha256'], stock_passed=sum(old.values()),
                candidate_passed=sum(new.values()), improved=sorted(t for t in new if new[t] and not old[t]),
                regressed=sorted(t for t in new if old[t] and not new[t]))
