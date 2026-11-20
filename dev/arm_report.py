"""Control/treatment report for a `dev.factory pilot --arm` job (development suites only).

Writes ARMS_DIR/arms-report.md with, per base:

* stock, control and treatment scores per category with Wilson 95% intervals;
* the treatment-vs-control gate and task gains/losses;
* each clarification task's outcome, separating relevant asks from irrelevant ones;
* every failed task that ended in `done`, with its answer and final observation, for semantic
  review of false-success claims (the counter alone does not establish one);
* median model and episode seconds.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev.v2_report import SUITES


def clarification_outcome(verdict):
    model = verdict['model']
    if model['terminal'] == 'ask':
        return 'relevant ask' if verdict['passed'] else 'irrelevant ask'
    if model['terminal'] in ('budget', 'invalid'):
        return model['terminal']
    return 'acted with changes' if model['changes'] else 'done without asking'


def _tasks(root):
    for suite, tasks in SUITES.items():
        for task_id, task in tasks.items():
            yield task_id, task, json.loads((Path(root) / suite / f'task_{task_id}.json').read_text())


def clarifications(root):
    return {task_id: {'outcome': clarification_outcome(v), 'answer': v['model']['answer']}
            for task_id, task, v in _tasks(root) if task.oracle[-1].split('\n', 1)[0] == 'ask'}


def failed_done(root):
    rows = []
    for task_id, task, v in _tasks(root):
        model = v['model']
        if model['terminal'] == 'done' and not v['passed']:
            last = model['events'][-1]['observation'] if model['events'] else ''
            rows.append({'task': task_id, 'answer': model['answer'], 'last_observation': last,
                         'last_is_error': bool(model['events'] and model['events'][-1]['is_error']),
                         'reasons': (model['failures'] or [])[:2]})
    return rows


def _pct(ci):
    return f'{ci[0]:.0%}–{ci[1]:.0%}'


def markdown(directory):
    directory = Path(directory)
    arms = json.loads((directory / 'arms.json').read_text())
    comps = {arm: json.loads((directory / arm / 'comparison.json').read_text()) for arm in ('control', 'treatment')}
    lines = [f'# Control vs treatment: {directory.name}', '',
             f"Control data `{arms['arms']['control']}`; treatment data `{arms['arms']['treatment']}`.", '']
    for base, versus in arms['treatment_vs_control'].items():
        stock = comps['control']['bases'][base]['stock']
        control = comps['control']['bases'][base]['tuned']
        treat = comps['treatment']['bases'][base]['tuned']
        lines += [f'## {base}', '',
                  f"Stock {stock['passed']}/{stock['total']} ({_pct(stock['ci95'])}); control {control['passed']}/"
                  f"{control['total']} ({_pct(control['ci95'])}); treatment {treat['passed']}/{treat['total']} "
                  f"({_pct(treat['ci95'])}). Treatment vs control: {len(versus['improved'])} gained, "
                  f"{len(versus['regressed'])} lost.", '',
                  '| Category | n | Stock | Control | Treatment | Treatment 95% CI |', '|---|---:|---:|---:|---:|---|']
        for cat, row in stock['categories'].items():
            lines.append(f"| {cat} | {row['total']} | {row['passed']} | {control['categories'][cat]['passed']} | "
                         f"{treat['categories'][cat]['passed']} | {_pct(treat['categories'][cat]['ci95'])} |")
        lines += ['', '| Counter | Stock | Control | Treatment |', '|---|---:|---:|---:|']
        for label, key in (('pending/rejected observations', 'policy_stops'), ('failed tasks ending in done', 'false_done')):
            lines.append(f'| {label} | {stock[key]} | {control[key]} | {treat[key]} |')
        for terminal in ('ask', 'budget', 'invalid'):
            lines.append(f"| terminal {terminal} | {stock['terminals'].get(terminal, 0)} | "
                         f"{control['terminals'].get(terminal, 0)} | {treat['terminals'].get(terminal, 0)} |")
        for label, key in (('median model s', 'median_model_seconds'), ('median episode s', 'median_episode_seconds')):
            lines.append(f'| {label} (Fast12, broad) | ' + ' | '.join(
                f"{x[key]['fast12']:.2f}, {x[key]['broad']:.2f}" for x in (stock, control, treat)) + ' |')
        lines += ['', 'Treatment vs control gate: ' + ', '.join(f"{k}={'yes' if v else 'no'}"
                                                           for k, v in versus['gate'].items()),
                  '', 'Gained vs control: ' + (', '.join(versus['improved']) or 'none'),
                  '', 'Lost vs control: ' + (', '.join(versus['regressed']) or 'none'), '']
        lines += _training_and_behaviour(directory, base, comps)
        cc = clarifications(directory / 'control' / base / 'tuned')
        tc = clarifications(directory / 'treatment' / base / 'tuned')
        if cc:
            lines += ['| Clarification task | Control | Treatment |', '|---|---|---|']
        for task_id in cc:
            lines.append(f"| {task_id} | {cc[task_id]['outcome']} | {tc[task_id]['outcome']}: "
                         f"{(tc[task_id]['answer'] or '').replace('|', '/')[:120]} |")
        lines.append('')
    return '\n'.join(lines)


def _training_and_behaviour(directory, base, comps):
    """Paired training fit (same fit rows in both arms), trace behaviour checks for every scored
    side, and the earlier adapter re-scored in the control arm (the data effect), when present."""
    from dev import v2_behaviour
    lines = []
    reports = {arm: directory / arm / base / 'training' / 'train-report.json' for arm in ('control', 'treatment')}
    if all(path.is_file() for path in reports.values()):
        train = {arm: json.loads(path.read_text()) for arm, path in reports.items()}
        paired = len({t.get('fit_rows_sha256') for t in train.values()}) == 1 and None not in {
            t.get('fit_rows_sha256') for t in train.values()}
        lines += [f"Training fit on the same {train['control']['fit_rows']} verified rows in both arms: "
                  f"{'yes' if paired else 'NO (not paired)'}.", '',
                  '| Arm | Schedule | Steps | Decision fit | Token fit | Weighted loss | Last LR | Seconds |',
                  '|---|---|---:|---:|---:|---:|---:|---:|']
        for arm, t in train.items():
            last = t['epochs'][-1]
            lines.append(f"| {arm} | {t['params'].get('lr_schedule', 'constant')} | {t['optimizer_steps']} | "
                         f"{last['decision_accuracy']:.2%} | {last['token_accuracy']:.2%} | "
                         f"{last['weighted_loss']:.4f} | {last.get('last_lr', t['params']['lr']):.2e} | {t['seconds']} |")
        lines.append('')
    sides = {'stock': directory / 'control' / base / 'stock'}
    if (directory / 'control' / base / 'previous').is_dir():
        sides['earlier adapter'] = directory / 'control' / base / 'previous'
    sides['control'] = directory / 'control' / base / 'tuned'
    sides['treatment'] = directory / 'treatment' / base / 'tuned'
    checks = {label: v2_behaviour.check(path) for label, path in sides.items()}
    lines += ['| Behaviour (from traces) | ' + ' | '.join(checks) + ' |', '|---|' + '---:|' * len(checks)]
    for key, label in (('missing_answers', 'missing answers (all terminals)'),
                       ('answer_omissions', 'bare-done question omissions'), ('input_edits', 'input edits'),
                       ('do_not_modify_edits', 'edits in do-not-modify tasks'),
                       ('read_only_changes', 'all effects on answer-only tasks'),
                       ('do_not_modify_changes', 'all effects where changes explicitly forbidden'),
                       ('unexpected_policy_stops', 'unexpected policy stops'),
                       ('answered_misses', 'answered but failed (review)')):
        lines.append(f'| {label} | ' + ' | '.join(str(c['counts'][key]) for c in checks.values()) + ' |')
    lines.append('')
    for label, c in checks.items():
        if label == 'stock':
            continue
        for key in ('answer_omissions', 'do_not_modify_changes', 'input_edits'):
            if c[key]:
                lines.append(f'- {label} {key.replace("_", " ")}: '
                             + ', '.join(x if isinstance(x, str) else f"{x['task']} ({', '.join(x['paths'])})"
                                         for x in c[key]))
    reference = comps['control']['bases'][base].get('reference')
    if reference:
        lines += ['', f"Data effect (earlier adapter re-scored here, same evaluation: "
                  f"{'yes' if reference['same_evaluation'] else 'no'}): earlier "
                  f"{reference['previous']['passed']}/80, control gains {len(reference['improved'])} "
                  f"({', '.join(reference['improved']) or 'none'}), loses {len(reference['regressed'])} "
                  f"({', '.join(reference['regressed']) or 'none'})."]
    lines.append('')
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description='Control/treatment development report for a pilot --arm job.')
    parser.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    text = markdown(args.directory)
    (args.directory / 'arms-report.md').write_text(text + '\n')
    review = {f'{arm}/{base}': failed_done(args.directory / arm / base / 'tuned')
              for arm in ('control', 'treatment')
              for base in json.loads((args.directory / 'arms.json').read_text())['treatment_vs_control']}
    (args.directory / 'failed-done-review.json').write_text(json.dumps(review, indent=2) + '\n')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
