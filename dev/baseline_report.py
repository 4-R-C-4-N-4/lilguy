"""Step 5 baseline report: stock candidates through the same Fast12 loop, one table.

Usage: python -m dev.baseline_report BASELINES.tsv [--reference LABEL ...] > report.md
BASELINES.tsv rows are `label<TAB>report dir<TAB>exit code`, as written by dev/baselines.sh.
Development tasks only; never reads the held-out suite.
"""
import argparse
import json
import math
import statistics
from pathlib import Path

from lilguy.loop import policy_of


def wilson(passed, total, z=1.96):
    if total == 0:
        return 0.0, 1.0
    p = passed / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centre - half), min(1.0, centre + half)


def summarize(directory):
    directory = Path(directory)
    identity = json.loads((directory / 'identity.json').read_text())
    summary = json.loads((directory / 'fast12.json').read_text())
    tasks = summary['tasks']
    if summary['infra_failures'] or any(t['infra_failure'] for t in tasks):
        raise ValueError(f'{directory.name}: infrastructure failures; rerun before reporting')
    policy_stops = 0
    for task in tasks:
        verdict = json.loads((directory / f"task_{task['task']}.json").read_text())
        policy_stops += sum(policy_of(e['observation']) in ('pending', 'rejected')
                            for e in verdict['model']['events'])
    metrics = [t['metrics'] for t in tasks]
    passed, total = summary['passed'], summary['total']
    low, high = wilson(passed, total)
    completion = sum(m['completion_tokens'] for m in metrics)
    model_seconds = sum(m['model_seconds'] for m in metrics)
    return dict(
        device=identity['device'], evaluation=identity['evaluation_sha256'], passed=passed, total=total,
        ci_low=low, ci_high=high, invalid=sum(t['terminal'] == 'invalid' for t in tasks),
        asks=sum(t['terminal'] == 'ask' for t in tasks),
        budget=sum(t['terminal'] == 'budget' for t in tasks),
        false_done=sum(t['terminal'] == 'done' and not t['passed'] for t in tasks),
        policy_stops=policy_stops, completion_tokens=completion,
        tokens_per_second=completion / model_seconds if model_seconds else 0.0,
        median_model_seconds=statistics.median(m['model_seconds'] for m in metrics),
        passed_tasks=sorted(t['task'] for t in tasks if t['passed']))


def markdown(runs, references):
    rows = [(label, summarize(d)) for label, d in runs]
    if len({s['evaluation'] for _, s in rows}) > 1:
        raise ValueError('runs use different evaluation fingerprints; rerun under one harness')
    if len({s['device'] for _, s in rows}) > 1:
        raise ValueError('runs used different devices; latency is not comparable')
    medians = {label: s['median_model_seconds'] for label, s in rows}
    head = ['model', 'pass', '95% CI', 'done but failed', 'asks', 'budget', 'invalid', 'policy stops',
            'gen tok/s', 'median model s/task'] + [f'latency vs {r}' for r in references]
    lines = ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
    for label, s in rows:
        cells = [label, f"{s['passed']}/{s['total']}", f"{s['ci_low']:.0%}-{s['ci_high']:.0%}",
                 str(s['false_done']), str(s['asks']), str(s['budget']), str(s['invalid']),
                 str(s['policy_stops']), f"{s['tokens_per_second']:.0f}", f"{s['median_model_seconds']:.2f}"]
        cells += [f"{s['median_model_seconds'] / medians[r]:.1%}" if medians[r] else 'n/a' for r in references]
        lines.append('| ' + ' | '.join(cells) + ' |')
    device = rows[0][1]['device'] if rows else 'none'
    lines += ['', f'Device: {device}. Evaluation fingerprint: {rows[0][1]["evaluation"][:12] if rows else "none"}.',
              'Latency is the median per-task model time on the same device and harness; '
              'quantization differs between candidates.', '', 'Tasks passed:']
    lines += [f"- {label}: {', '.join(s['passed_tasks']) or 'none'}" for label, s in rows]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baselines', type=Path)
    parser.add_argument('--reference', action='append', default=[])
    args = parser.parse_args(argv)
    runs = [(label, Path(d)) for label, d, _ in
            (line.split('\t') for line in args.baselines.read_text().splitlines() if line.strip())]
    print(markdown(runs, args.reference), end='')


if __name__ == '__main__':
    main()
