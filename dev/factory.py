"""Operator entry point for repeatable factory jobs; never an agent tool."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from lilguy.protocol import INTERFACE_VERSION

ROOT = Path(__file__).resolve().parents[1]


def fast12_identity(model, server):
    def sha(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    sources = [ROOT / p for p in ('dev/fast12.py', 'dev/fast12_runner.py', 'toolset.yaml', 'policy.yaml')]
    sources.extend(sorted((ROOT / 'lilguy').rglob('*.py')))
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    inputs['llama-server'] = sha(server)
    return {'gguf_sha256': sha(model), 'evaluation_inputs': inputs,
            'evaluation_sha256': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()}


def all_executed(path):
    try:
        cases = ET.parse(path).findall('.//testcase')
    except (ET.ParseError, OSError):
        return False
    return bool(cases) and not any(c.find(tag) is not None for c in cases for tag in ('skipped', 'failure', 'error'))


def evaluation_gate(pin_path=ROOT / 'dev/holdout_manifest.sha256'):
    """Audit every development task against the frozen held-out suite before a model job."""
    from dev import broad_dev, fast12
    from dev.eval_gate import verify
    rows = [dict(id=t.id, split='dev', template_id=t.id, request=t.request, files=t.files)
            for t in (*fast12.TASKS, *broad_dev.TASKS)]
    try:
        pin = Path(pin_path).read_text().split()[0]
    except (OSError, IndexError):
        return {'ok': False, 'reason': 'held-out suite is not frozen'}
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / 'development.json'
        manifest.write_text(json.dumps(rows))
        return verify(ROOT / 'dev/holdout_manifest.json', pin, manifest)


def execute(directory, stages):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()

    report = {'interface': INTERFACE_VERSION, 'revision': git('rev-parse', 'HEAD'),
              'dirty': bool(git('status', '--porcelain')), 'status': 'running', 'stages': []}
    def save():
        tmp = directory / 'result.tmp'
        tmp.write_text(json.dumps(report, indent=2) + '\n')
        tmp.replace(directory / 'result.json')
    save()
    for name, argv, evidence in stages:
        started = time.monotonic()
        print(name, flush=True)
        with (directory / f'{name}.log').open('w') as log:
            try:
                rc = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                    env={**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                                         'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}).returncode
            except OSError as exc:
                print(str(exc), file=log)
                rc = 1
        ok = rc == 0 and (evidence is None or all_executed(evidence))
        report['stages'].append({'name': name, 'argv': list(map(str, argv)), 'exit': rc, 'passed': ok,
                                 'seconds': round(time.monotonic() - started, 3)})
        if not ok:
            report['status'] = 'failed'
            save()
            print(f'FAILED: see {directory}/{name}.log')
            return 1
        save()
    report['status'] = 'passed'
    save()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', choices=['check', 'trial', 'fast12', 'audit-splits', 'compare'])
    parser.add_argument('--stock', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--held-out', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--held-out-sha256', help='previously pinned digest; never derive from current input')
    parser.add_argument('--gguf', type=Path)
    parser.add_argument('--server', type=Path, default=Path(os.environ.get('LLAMA_SERVER', Path.home() / 'programs/llama.cpp/build/bin/llama-server')))
    args = parser.parse_args()
    if args.job == 'compare':
        from dev.fast12_compare import compare
        if not (args.stock and args.candidate):
            parser.error('compare needs --stock and --candidate Fast12 report directories')
        try:
            print(json.dumps(compare(args.stock, args.candidate), sort_keys=True))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            parser.exit(1, f'Cannot compare Fast12 reports: {exc}\n')
        return 0
    if args.job == 'audit-splits':
        from dev.eval_gate import verify
        if not (args.held_out and args.held_out_sha256 and args.manifest):
            parser.error('audit-splits requires --held-out, --held-out-sha256 and --manifest')
        result = verify(args.held_out, args.held_out_sha256, args.manifest)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['ok'] else 1
    if args.job != 'check' and not (args.gguf and args.gguf.is_file() and args.server.is_file()):
        parser.error(f'{args.job} needs a local --gguf and llama-server (--server or LLAMA_SERVER)')
    if args.job != 'check':
        gate = evaluation_gate()
        if not gate['ok']:
            parser.exit(1, f"Evaluation gate failed: {gate['reason']}\n")
    base = ROOT / 'reports' / 'factory'
    base.mkdir(parents=True, exist_ok=True)
    with (base / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(2, 'Another factory job owns the sandbox gate.\n')
        directory = Path(tempfile.mkdtemp(prefix=args.job + '-', dir=base))
        print(directory, flush=True)
        if args.job == 'fast12':
            (directory / 'identity.json').write_text(json.dumps(fast12_identity(args.gguf, args.server),
                                                                indent=2, sort_keys=True) + '\n')
            return execute(directory, [('dev-suite', ['.venv/bin/python', '-m', 'dev.fast12_runner',
                args.server.resolve(), args.gguf.resolve(), directory], None)])
        if args.job == 'trial':
            return execute(directory, [('dev-task', ['.venv/bin/python', '-m', 'dev.factory_trial',
                args.server.resolve(), args.gguf.resolve(), directory], None)])
        stages = []
        for name, cmd in [('protocol', ['.venv/bin/python', '-m', 'pytest', '-q', 'tests/unit/test_protocol.py']),
                          ('split-protection', ['.venv/bin/python', '-m', 'pytest', '-q',
                                                'tests/unit/test_split_audit.py', 'tests/unit/test_eval_gate.py']),
                          ('guarded-tools', ['.venv/bin/python', '-m', 'pytest', '-q',
                                            'tests/unit/test_mcp_server_v1.py', 'tests/unit/test_typed_step_fs.py',
                                            'tests/sandbox/test_mcp_server_v1_live.py']),
                          # Step 2 acceptance. Corpus #17 needs rsync, absent on this host; it is
                          # deselected by name so the gap stays visible in the job record.
                          ('v1-bypass-corpus', ['.venv/bin/python', '-m', 'pytest', '-q',
                                                'tests/bypass/test_v1_run_corpus.py', '--deselect',
                                                'tests/bypass/test_v1_run_corpus.py::'
                                                'test_corpus_through_v1_run_never_commits[17]']),
                          ('trainer-smoke', ['dev/train_tests.sh'])]:
            evidence = directory / f'{name}.xml'
            stages.append((name, [*cmd, f'--junitxml={evidence}'], evidence))
        return execute(directory, stages)


if __name__ == '__main__':
    raise SystemExit(main())
