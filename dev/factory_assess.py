"""Offline assessment for matched pilot arms. No weights, server, sandbox or GPU."""
from functools import lru_cache
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import tempfile

from dev import v2_report
from lilguy import protocol as p

FOCUS = ('emit_literal_print_script', 'repair_unclosed_shell_branch',
         'exact_match_required_edit', 'restrict_local_draft_mode')


@lru_cache
def tools():
    return p.load_tools()


def prefix(request, row, turn):
    events = row['model']['events']
    if not 0 <= turn < len(events):
        raise ValueError('turn must index a recorded tool decision')
    version = row['interface']
    messages = [{'role': 'system', 'content': p.system_prompt(tools(), version)},
                {'role': 'user', 'content': p.user_message(request, row['mode'], version)}]
    for event in events[:turn]:
        messages.extend([{'role': 'assistant', 'content': p.render_action(p.Action(**event['action']), tools(), version)},
                         {'role': 'user', 'content': p.observation_message(event['observation'])}])
    return messages


def check_trace(row, task, passed):
    if (row['task'] != task or row['passed'] is not passed or row['infra_failure']
            or not row['model']['original_unchanged']):
        raise ValueError(f'invalid trace or disagreement with summary: {task}')


def assess(job, base):
    job = Path(job).resolve()
    if Path(base).name != base or base in ('', '.', '..'):
        raise ValueError('invalid base key')
    arms = json.loads((job / 'arms.json').read_text())
    sides = {'stock': job/'control'/base/'stock', 'control': job/'control'/base/'tuned',
             'treatment': job/'treatment'/base/'tuned'}
    summaries = {k: v2_report.side_summary(path) for k, path in sides.items()}
    for key in ('device', 'evaluation_sha256', 'interface'):
        if any(s[key] != summaries['stock'][key] for s in summaries.values()):
            raise ValueError(f'unmatched {key}')
    rows, probes = [], []
    repo = Path(__file__).resolve().parents[1]
    for suite, roster in v2_report.SUITES.items():
        inputs = json.loads((sides['stock']/suite/'identity.json').read_text())['evaluation_inputs']
        for name, digest in inputs.items():
            if name.startswith('dev/') or name in ('toolset.yaml', 'lilguy/protocol.py'):
                if not (repo/name).resolve().is_relative_to(repo) or sha256((repo/name).read_bytes()).hexdigest() != digest:
                    raise ValueError(f'current prompt/task inputs differ from recording: {name}')
        for task, spec in roster.items():
            row = {'task': task, 'request': spec.request, 'sides': {}}
            for label, path in sides.items():
                v = json.loads((path/suite/f'task_{task}.json').read_text())
                check_trace(v, task, task in summaries[label]['passed_tasks'])
                if v['interface'] != summaries[label]['interface']:
                    raise ValueError(f'trace interface mismatch: {task}')
                m = v['model']
                row['sides'][label] = dict(passed=v['passed'], **{k: m[k] for k in ('events','terminal','failures','changes')})
                row['expected_changes'] = v['oracle']['changes']
                if task in FOCUS:
                    for i, event in enumerate(m['events']):
                        probes.append(dict(task=task, source=label, turn=i, messages=prefix(spec.request, v, i),
                                           observed_action=event['action'], interface=v['interface']))
            rows.append(row)
    out = Path(tempfile.mkdtemp(prefix='assessment-', dir=job))
    (out/'assessment.json').write_text(json.dumps(dict(arms=arms['arms'], summaries=summaries, rows=rows)))
    (out/'prefixes.jsonl').write_text(''.join(json.dumps(q)+'\n' for q in probes))
    html = ['<!doctype html><meta charset=utf-8><title>Factory assessment</title><style>body{font:16px system-ui;margin:2em}pre{white-space:pre-wrap;overflow-wrap:anywhere}td,th{vertical-align:top;padding:.4em}table{width:100%;table-layout:fixed}summary{cursor:pointer}</style>',
            '<h1>Development assessment</h1><p>Stock / control / treatment. Expand a task to inspect recorded actions, observations and staged bytes. A different action is not necessarily an error.</p>',
            '<p>'+escape(str(arms['arms']))+'</p>']
    for row in sorted(rows, key=lambda r: (r['task'] not in FOCUS, r['task'])):
        verdicts = ' / '.join('pass' if m['passed'] else 'miss' for m in row['sides'].values())
        html.extend([f'<details><summary>{escape(row["task"])} — {verdicts}</summary>',
                     '<p>'+escape(row['request'])+'</p><pre>Expected effects: '+escape(json.dumps(row['expected_changes'], indent=2))+'</pre><table><tr>'])
        for label, m in row['sides'].items():
            html.append('<td><b>'+label+'</b><pre>'+escape(json.dumps(m, indent=2, ensure_ascii=False))+'</pre></td>')
        html.append('</tr></table></details>')
    (out/'index.html').write_text('\n'.join(html))
    return out
