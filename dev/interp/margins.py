"""Decision margins at every lost roster task of a round (interpretability lesson 5).

    $TRAIN_PY -m dev.interp.margins OUT --candidate PILOT [--candidate PILOT ...]

For each candidate pilot (one trained seed each), the tasks the reference (2.0 on interface v5,
`fast12-bazwwl4u` + `broad-t887e76u`) passes and any candidate fails. At each one, the first
action where the failing trace left the reference trace is scored: log P(failing action) - log
P(reference action), in nats, under every candidate, the reference and the stock base.

  >= 2 at the failing seed      habit          (the model really prefers the mistake)
  |m| < 1                       coin flip      (data should not be written for it)
  <= -2                         not reproduced (bf16 prefers the right action; a Q8_0 greedy miss)
  otherwise                     lean

A loss is *actionable* (evidence for new training data) only if it is a habit at every seed
that lost it, and at two seeds or more. Writes margins.json and margins.md. Development traces
only; never a held-out suite.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev.interp import common as c

REFERENCE = 'r10_2_0'


def classify(m):
    return 'habit' if m >= 2 else 'coin flip' if abs(m) < 1 else 'not reproduced' if m <= -2 else 'lean'


def label_of(pilot):
    plan = json.loads((c.FACTORY / pilot / 'plan.json').read_text())
    revision = Path(plan['data']['path']).name.split('-')[-1]
    return f"{revision}_s{plan.get('train_seed')}"


def lost(candidates):
    ids = sorted({Path(f).name[5:-5] for d in c.RUNS[REFERENCE] for f in (c.FACTORY / d).glob('task_*.json')})
    return [t for t in ids if c.verdict(REFERENCE, t)['passed']
            and any(not c.verdict(label, t)['passed'] for label in candidates)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('out', type=Path)
    ap.add_argument('--candidate', action='append', required=True, metavar='PILOT',
                    help='pilot directory name under reports/factory (repeat per seed)')
    ap.add_argument('--reference-runs', metavar='FAST12,BROAD',
                    help="2.0's roster runs (default: the 80-task v5 runs); use after the roster grows")
    ap.add_argument('--runs', action='append', default=[], metavar='PILOT=FAST12,BROAD',
                    help="a candidate's roster runs when they are not the ones inside its pilot")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.reference_runs:
        c.RUNS[REFERENCE] = args.reference_runs.split(',')
    override = dict(item.split('=', 1) for item in args.runs)
    candidates = []
    for pilot in args.candidate:
        label = label_of(pilot)
        c.register(label, pilot)
        if pilot in override:
            c.RUNS[label] = override[pilot].split(',')
        candidates.append(label)
    lab = c.Lab([REFERENCE, *candidates])
    rows = []
    for task in lost(candidates):
        for seed in candidates:
            found = c.divergence(task, seed, REFERENCE)
            if found is None:
                continue
            msgs, mistake, correct, step = found
            head = lab.head(msgs)
            margin = {}
            for label in ['stock', REFERENCE, *candidates]:
                with lab.use(label):
                    margin[label] = round(lab.margin(head, mistake, correct), 2)
            harmless = step == 0 and mistake.split('\n', 1)[0] in ('tool fs.read', 'tool fs.list', 'tool fs.find')
            rows.append(dict(task=task, failing=seed, step=step, mistake=mistake, correct=correct, margin=margin,
                             verdict='harmless first look' if harmless else classify(margin[seed])))
            print(f"{task:38} {seed:10} step {step} {rows[-1]['verdict']:19} " +
                  ' '.join(f'{k}={v:+.1f}' for k, v in margin.items()), flush=True)
    by_task = {}
    for row in rows:
        by_task.setdefault(row['task'], []).append(row)
    actionable = sorted(t for t, rs in by_task.items()
                        if len(rs) >= 2 and all(r['verdict'] == 'habit' for r in rs))
    summary = {'reference': REFERENCE, 'candidates': dict(zip(candidates, args.candidate)), 'lost_tasks': len(by_task),
               'verdicts': {v: sum(r['verdict'] == v for r in rows) for v in
                            ('habit', 'lean', 'coin flip', 'not reproduced', 'harmless first look')},
               'actionable': actionable, 'rows': rows}
    (args.out / 'margins.json').write_text(json.dumps(summary, indent=1) + '\n')
    lines = [f'# Decision margins: {", ".join(candidates)} vs {REFERENCE} (interface v5)', '',
             f"{len(by_task)} lost tasks; actionable (habit at every losing seed, two or more seeds): "
             f"{', '.join(actionable) or 'none'}", '',
             '| task | seed | step | verdict | ' + ' | '.join(['stock', REFERENCE, *candidates]) + ' |',
             '|---|---|---|---|' + '---|' * (2 + len(candidates))]
    for r in rows:
        lines.append(f"| `{r['task']}` | {r['failing']} | {r['step']} | {r['verdict']} | " +
                     ' | '.join(f"{r['margin'][k]:+.1f}" for k in ['stock', REFERENCE, *candidates]) + ' |')
    (args.out / 'margins.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
