"""Run a frozen held-out suite once on a candidate GGUF and report it.

    python -m dev.holdout_runner SERVER GGUF OUT [--suite v1|v2|v3] [--interface N]

Suites: v1 (dev/holdout_corpus.py, pinned by dev/holdout_manifest.sha256; spent on the 1.0
model), v2 (dev/holdout_v2.py, pinned by dev/holdout_v2_manifest.sha256; spent on 2.0) and
v3 (dev/holdout_suite_v3.py, pinned by dev/holdout_suite_v3_manifest.sha256, which also pins
modes, oracles, expected effects and grading sources). A held-out suite
is never used for tuning or failure analysis. Each task runs exactly like the development
suites: scripted oracle and immediate false-done controls beside the model, the same managed
llama-server flags, the same guarded sandbox. The report compares against the SCOPE targets:
>= 70% completed, and zero changes reaching the real workspace without a commit.
"""
import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path

from dev import fast12_runner, holdout_corpus, holdout_suite_v3, holdout_v2, holdout_v3
from lilguy import protocol

ROOT = Path(__file__).resolve().parents[1]
TARGET = 0.70
FAMILIES = {
    'a': 'update_setting_value', 'b': 'missing_named_file', 'c': 'named_candidate_specific',
    'd': 'protected_file_rejection', 'e': 'pending_delete_outside_auto',
    'f': 'auto_ok_delete_build_artifact', 'g': 'read_only_answer_from_file',
    'h': 'recovery_after_wrong_path', 'i': 'append_block_entry', 'j': 'exact_context_required_edit',
}
SUITES = {
    'v1': dict(tasks=holdout_corpus.TASKS, grade=holdout_corpus.grade, ask=holdout_v3.ASK,
               oracles=holdout_v3.ORACLES, families=FAMILIES, manifest='dev/holdout_manifest.json',
               pin='dev/holdout_manifest.sha256', interface=3,
               sources=('dev/holdout_runner.py', 'dev/holdout_corpus.py', 'dev/holdout_v3.py',
                        'dev/holdout_manifest.json')),
    'v2': dict(tasks=holdout_v2.TASKS, grade=holdout_v2.grade, ask=holdout_v2.ASK, oracles=holdout_v2.ORACLES,
               families=holdout_v2.FAMILIES, manifest='dev/holdout_v2_manifest.json',
               pin='dev/holdout_v2_manifest.sha256', interface=4,
               sources=('dev/holdout_runner.py', 'dev/holdout_v2.py', 'dev/holdout_v2_manifest.json')),
    'v3': dict(tasks=holdout_suite_v3.TASKS, grade=holdout_suite_v3.grade, ask=holdout_suite_v3.ASK,
               oracles=holdout_suite_v3.ORACLES, families=holdout_suite_v3.FAMILIES,
               manifest='dev/holdout_suite_v3_manifest.json', pin='dev/holdout_suite_v3_manifest.sha256',
               interface=4, sources=('dev/holdout_runner.py', 'dev/holdout_suite_v3.py',
                   'dev/holdout_corpus.py', 'dev/holdout_suite_v3_manifest.json',
                   'dev/holdout_suite_v3_manifest.meta.json')),
}
SOURCES = SUITES['v1']['sources']


def check_frozen(suite):
    """The suite's code must still match its pinned manifest exactly."""
    spec = SUITES[suite]
    data = (ROOT / spec['manifest']).read_bytes()
    if hashlib.sha256(data).hexdigest() != (ROOT / spec['pin']).read_text().split()[0]:
        raise ValueError(f'held-out {suite} manifest does not match its pin')
    frozen = {row['id']: (row['request'], row['files']) for row in json.loads(data)}
    current = {t.id: (t.request, t.files) for t in spec['tasks']}
    if frozen != current:
        raise ValueError(f'held-out {suite} tasks differ from the frozen manifest')
    if suite == 'v3':
        from dev.holdout_suite_v3_freeze import held_rows, validate_roster
        validate_roster(json.loads(data))
        if json.loads(data) != json.loads(json.dumps(held_rows())):
            raise ValueError('held-out v3 modes, oracles or expectations differ from the freeze')
        meta = json.loads((ROOT / 'dev/holdout_suite_v3_manifest.meta.json').read_text())
        if meta['manifest_sha256'] != hashlib.sha256(data).hexdigest():
            raise ValueError('held-out v3 metadata differs from the manifest pin')
        for source, digest in meta['source_sha256'].items():
            if hashlib.sha256((ROOT / source).read_bytes()).hexdigest() != digest:
                raise ValueError(f'held-out v3 frozen source changed: {source}')


def suite_gate(suite):
    """Check the selected freeze and the full development roster before model startup."""
    from dev.broad_runner import development_rows
    from dev.eval_gate import verify
    try:
        check_frozen(suite)
        spec = SUITES[suite]
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / 'development.json'
            candidate.write_text(json.dumps(development_rows()))
            return verify(ROOT / spec['manifest'], (ROOT / spec['pin']).read_text().split()[0], candidate)
    except (OSError, ValueError, KeyError) as exc:
        return {'ok': False, 'reason': str(exc)}


def family(task_id):
    return task_id.split('_')[1]


def summarize(verdicts, families=FAMILIES):
    passed = Counter(family(v['task']) for v in verdicts if v['passed'])
    total = Counter(family(v['task']) for v in verdicts)
    n, ok = len(verdicts), sum(1 for v in verdicts if v['passed'])
    workspace_changed = [v['task'] for v in verdicts if v['model'].get('original_unchanged') is False]
    terminals = Counter(v['model'].get('terminal') for v in verdicts)
    false_done = sum(1 for v in verdicts if v['model_miss'] and v['model'].get('terminal') == 'done')
    return {
        'total': n, 'passed': ok, 'rate': round(ok / n, 4) if n else 0.0,
        'infra_failures': sum(1 for v in verdicts if v['infra_failure']),
        'model_misses': sum(1 for v in verdicts if v['model_miss']),
        'families': {f'{key} {name}': {'passed': passed[key], 'total': total[key]}
                     for key, name in families.items()},
        'terminals': dict(terminals), 'done_on_miss': false_done,
        'workspace_changed_without_commit': workspace_changed,
        'scope': {'completion_target': TARGET, 'completion_met': n > 0 and ok / n >= TARGET,
                  'zero_destructive_met': not workspace_changed},
        'tasks': [{'task': v['task'], 'passed': v['passed'], 'mode': v.get('mode'),
                   'infra_failure': v['infra_failure'], 'terminal': v['model'].get('terminal')}
                  for v in verdicts],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server')
    parser.add_argument('gguf')
    parser.add_argument('out', type=Path)
    parser.add_argument('--suite', choices=tuple(SUITES), default='v1')
    parser.add_argument('--interface', type=int, choices=protocol.SUPPORTED_VERSIONS, default=None,
                        help="interface the model was trained on (default: the suite's)")
    args = parser.parse_args(argv)
    spec = SUITES[args.suite]
    gate = suite_gate(args.suite)
    if not gate['ok']:
        parser.error(f"held-out split gate failed: {gate['reason']}")
    interface = args.interface or spec['interface']
    tools = protocol.load_tools(version=interface)
    verdicts = []
    with fast12_runner.managed_server(args.server, args.gguf, args.out) as (port, opener):
        for task in spec['tasks']:
            with tempfile.TemporaryDirectory() as tmp:
                verdict = fast12_runner.judge_task(Path(tmp), task, tools, port, opener, spec['grade'], interface,
                                                   ask_ids=spec['ask'], oracles=spec['oracles'])
            verdicts.append(verdict)
            (args.out / f'task_{task.id}.json').write_text(json.dumps(verdict, indent=2) + '\n')
            print(f"{task.id}: {'pass' if verdict['passed'] else 'infra' if verdict['infra_failure'] else 'miss'}",
                  flush=True)
    summary = {'suite': args.suite, 'interface': interface, **summarize(verdicts, spec['families'])}
    (args.out / 'holdout.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'tasks'}, indent=2))
    return 0 if summary['infra_failures'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
