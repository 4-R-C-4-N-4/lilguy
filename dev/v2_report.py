"""Stock-vs-tuned development comparison for a v2 pilot job (never reads the held-out suite)."""
import json
from pathlib import Path

from dev import broad_runner, dev_categories, fast12, factory_screen
from dev.baseline_report import wilson

SUITES = {'fast12': {t.id: t for t in fast12.TASKS}, 'broad': {t.id: t for t, _ in broad_runner.task_graders()}}


def side_summary(root):
    """Both suites for one model: per-suite summaries plus per-category pass rates with Wilson CIs."""
    suites, identities, passed = {}, {}, set()
    for suite, tasks in SUITES.items():
        identity, summary = factory_screen.summarize(Path(root) / suite, suite, tasks)
        suites[suite], identities[suite] = summary, identity
        passed |= set(summary['passed_tasks'])
    if identities['fast12']['gguf_sha256'] != identities['broad']['gguf_sha256']:
        raise ValueError(f'artifact changed between suites: {root}')
    if identities['fast12']['device'] != identities['broad']['device']:
        raise ValueError(f'device changed between suites: {root}')
    categories = {}
    for suite in SUITES.values():
        for task_id in suite:
            row = categories.setdefault(dev_categories.category(task_id), {'passed': 0, 'total': 0})
            row['total'] += 1
            row['passed'] += task_id in passed
    for row in categories.values():
        low, high = wilson(row['passed'], row['total'])
        row['rate'], row['ci95'] = row['passed'] / row['total'], [round(low, 3), round(high, 3)]
    total = sum(len(s) for s in SUITES.values())
    low, high = wilson(len(passed), total)
    return {'gguf_sha256': identities['fast12']['gguf_sha256'], 'device': identities['fast12']['device'],
            'evaluation_sha256': {k: v['evaluation_sha256'] for k, v in identities.items()},
            'passed': len(passed), 'total': total, 'ci95': [round(low, 3), round(high, 3)],
            'passed_tasks': sorted(passed), 'categories': dict(sorted(categories.items())),
            'policy_stops': sum(s['policy_stops'] for s in suites.values()),
            'false_done': sum(s['done_misses'] for s in suites.values()),
            'terminals': {t: sum(s['terminals'].get(t, 0) for s in suites.values())
                          for t in sorted({t for s in suites.values() for t in s['terminals']})},
            'correct_clarifications': sorted(c for s in suites.values() for c in s['correct_clarifications']),
            'clarification_total': sum(s['clarification_total'] for s in suites.values()),
            'median_episode_seconds': {k: s['median_episode_seconds'] for k, s in suites.items()},
            'median_model_seconds': {k: s['median_model_seconds'] for k, s in suites.items()},
            'suites': suites}


def compare_base(stock_root, tuned_root):
    stock, tuned = side_summary(stock_root), side_summary(tuned_root)
    if stock['evaluation_sha256'] != tuned['evaluation_sha256'] or stock['device'] != tuned['device']:
        raise ValueError('stock and tuned were not scored by the same evaluation on the same device')
    a, b = set(stock['passed_tasks']), set(tuned['passed_tasks'])
    per_category = {c: {'stock': stock['categories'][c]['passed'], 'tuned': tuned['categories'][c]['passed'],
                        'total': stock['categories'][c]['total']} for c in stock['categories']}
    gate = {
        'originals_preserved_and_infra_clean': True,  # summarize() refuses anything else
        'beats_stock_overall': len(b) > len(a),
        'no_category_regression': all(v['tuned'] >= v['stock'] for v in per_category.values()),
        'beats_stock_every_category': all(v['tuned'] > v['stock'] for v in per_category.values()),
        'no_extra_policy_stops': tuned['policy_stops'] <= stock['policy_stops'],
        'no_extra_false_done': tuned['false_done'] <= stock['false_done'],
    }
    return {'stock': stock, 'tuned': tuned, 'improved': sorted(b - a), 'regressed': sorted(a - b),
            'per_category': per_category, 'gate': gate}


def write(directory, bases):
    result = {'interface': 1, 'bases': {}}
    for base in bases:
        root = Path(directory) / base
        result['bases'][base] = compare_base(root / 'stock', root / 'tuned')
        train = root / 'training' / 'train-report.json'
        if train.is_file():
            report = json.loads(train.read_text())
            result['bases'][base]['training'] = {k: report[k] for k in (
                'repo', 'revision', 'rows', 'stop_reason', 'optimizer_steps', 'seconds', 'epochs', 'peak_gpu_mib',
                'train_tokens_per_second')}
    (Path(directory) / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    (Path(directory) / 'report.md').write_text(markdown(result) + '\n')
    return result


def markdown(result):
    """Per-base, per-category development table (stock vs tuned, Wilson 95% CI) plus safety counters."""
    lines = ['The legacy `false_done` / `no_extra_false_done` fields count failed tasks ending in '
             '`done`, not a count of confirmed false success claims. They include wrong effects '
             'and grader mismatches; inspect traces before making a semantic safety claim. '
             'Policy-stop counts are pending/rejected observations, including expected approval stops.', '']
    for base, r in result['bases'].items():
        st, tu = r['stock'], r['tuned']
        lines += [f'### {base}', '',
                  f"Overall: stock {st['passed']}/{st['total']} (95% CI {st['ci95'][0]:.0%}-{st['ci95'][1]:.0%}), "
                  f"tuned {tu['passed']}/{tu['total']} (95% CI {tu['ci95'][0]:.0%}-{tu['ci95'][1]:.0%}); "
                  f"{len(r['improved'])} gained, {len(r['regressed'])} lost.", '',
                  '| Category | n | Stock | Tuned | Tuned 95% CI |', '|---|---:|---:|---:|---|']
        for cat, row in r['per_category'].items():
            ci = tu['categories'][cat]['ci95']
            lines.append(f"| {cat} | {row['total']} | {row['stock']} | {row['tuned']} | {ci[0]:.0%}-{ci[1]:.0%} |")
        lines += ['', '| Counter | Stock | Tuned |', '|---|---:|---:|',
                  f"| correct clarifications (of {st['clarification_total']}) | {len(st['correct_clarifications'])} | "
                  f"{len(tu['correct_clarifications'])} |",
                  f"| policy stops (pending/rejected observations) | {st['policy_stops']} | {tu['policy_stops']} |",
                  f"| done on a failed task | {st['false_done']} | {tu['false_done']} |",
                  f"| budget exhausted | {st['terminals'].get('budget', 0)} | {tu['terminals'].get('budget', 0)} |",
                  f"| invalid action | {st['terminals'].get('invalid', 0)} | {tu['terminals'].get('invalid', 0)} |",
                  f"| median model s per episode (Fast12, broad) | {st['median_model_seconds']['fast12']:.2f}, "
                  f"{st['median_model_seconds']['broad']:.2f} | {tu['median_model_seconds']['fast12']:.2f}, "
                  f"{tu['median_model_seconds']['broad']:.2f} |",
                  f"| median episode s (Fast12, broad) | {st['median_episode_seconds']['fast12']:.2f}, "
                  f"{st['median_episode_seconds']['broad']:.2f} | {tu['median_episode_seconds']['fast12']:.2f}, "
                  f"{tu['median_episode_seconds']['broad']:.2f} |", '',
                  'Gate: ' + ', '.join(f"{k}={'yes' if v else 'no'}" for k, v in r['gate'].items()), '',
                  'Gained: ' + (', '.join(r['improved']) or 'none'), '',
                  'Lost: ' + (', '.join(r['regressed']) or 'none'), '']
    return '\n'.join(lines)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    result = json.loads((args.directory / 'comparison.json').read_text())
    text = markdown(result)
    (args.directory / 'report.md').write_text(text + '\n')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
