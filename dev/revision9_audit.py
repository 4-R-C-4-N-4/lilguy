"""Offline audit of paired development traces; no execution of model outputs."""
import json
from pathlib import Path
from statistics import median
from dev.dev_categories import category
from dev.v2_behaviour import traces


def main():
    root = Path('reports/factory')
    sources = ['pilot-i99_qvnk', 'pilot-vkuaegj1', 'pilot-p9tcy7s0/control', 'pilot-p9tcy7s0/treatment']
    bases = ['minicpm', 'qwen08']
    rows = {}
    for i, source in enumerate(sources):
        for b in bases:
            data = list(traces(root / source / b / 'tuned'))
            assert len(data) == 80 and all(not x['infra_failure'] and x['model']['original_unchanged'] for x in data)
            rows[i,b] = {x['task']: x for x in data}
    tasks = sorted(rows[0,bases[0]])
    assert len(tasks) == 80 and all(set(tasks) == set(d) for d in rows.values())
    report = ['# Revision 9 development evidence', '', 'Paired result grid: columns are r7/42, r8/42, r7/43, r8/43; + pass, - miss. Same 80 tasks in all eight runs; no held-out inference. A pass is the frozen grader verdict, not independent semantic approval.', '', '| Task | Category | MiniCPM | Qwen |', '|---|---|---|---|']
    for t in tasks:
        codes = [''.join('+' if rows[i,b][t]['passed'] else '-' for i in range(4)) for b in bases]
        report.append(f'| {t} | {category(t)} | {codes[0]} | {codes[1]} |')
    for i in (1,3):
        wins = [{t for t in tasks if rows[i,b][t]['passed']} for b in bases]
        shared = wins[0] & wins[1]
        report.extend(['', f'## R8 seed {42 if i == 1 else 43}: {len(shared)} shared successes', 'MiniCPM only: ' + ', '.join(sorted(wins[0]-wins[1])), 'Qwen only: ' + ', '.join(sorted(wins[1]-wins[0]))])
        for b in bases:
            report.append(f'{b}, medians on the same {len(shared)} successful tasks (seconds): ' + ', '.join(f'{key} {median(rows[i,b][t]["model"]["metrics"][key] for t in shared):.3f}' for key in ('model_seconds','episode_seconds')))
    report.extend(['','## Script audit: terminal, effects, failures and action sequence (all 24 traces)'])
    for t in tasks:
        if category(t) != 'scripts':
            continue
        report.append('\n### ' + t)
        for i,s in enumerate(sources):
            for b in bases:
                m = rows[i,b][t]['model']
                events = [f"{e['action']['tool'] or e['action']['text']} → {e['observation'].splitlines()[0]}" for e in m['events']]
                report.append(f"- {s}/{b}: {m['terminal']}; staged: {list(m['changes'])}; {', '.join(m['failures']) or 'pass'}. " + '; '.join(events).replace('\n',' / '))
    report.extend(['','## Historical wrong answers: all 19 agent-audited cases', 'Each line gives the earlier agent finding, followed by r8 grader outcomes on seeds 42 and 43 for the same base. A grader pass does not prove every semantic issue is fixed.'])
    n = 0
    for f in sorted(Path('docs/data').glob('ANSWER-COSINE-*COSINE-SEMANTIC-AUDIT.json')):
        for x in json.loads(f.read_text())['items']:
            if x['verdict'] != 'confirmed_wrong_answer':
                continue
            n += 1
            report.append(f"- {x['base']} / {x['task']}: {x['reason']} R8: " + ', '.join('pass' if rows[i,x['base']][x['task']]['passed'] else 'miss' for i in (1,3)))
    assert n == 19
    Path('docs/data/R9-DEVELOPMENT-AUDIT.md').write_text('\n'.join(report)+'\n')


if __name__ == '__main__':
    main()
