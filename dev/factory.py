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
V1_SAFETY_CASES = frozenset(
    ('tests.bypass.test_v1_run_corpus', f'test_corpus_through_v1_run_never_commits[{case}]')
    for case in ('1', '2', '3', '4', '5', '6', '7', '8', '17', '18', 'approval-spoof',
                 'chmod-one', 'chmod-tree', 'git-config', 'git-remove', 'dotenv',
                 'new-git-hook', 'new-nested-env')
)


def fast12_identity(model, server, *, extra_sources=(), interface=INTERFACE_VERSION):
    def sha(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    sources = [ROOT / p for p in ('dev/fast12.py', 'dev/fast12_runner.py', 'dev/oracles_v3.py', 'toolset.yaml',
                                  'policy.yaml', *extra_sources)]
    sources.extend(sorted((ROOT / 'lilguy').rglob('*.py')))
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    inputs['llama-server'] = sha(server)
    if interface != 1:  # v1 identities keep their historical evaluation hashes
        inputs['interface'] = str(interface)
    return {'gguf_sha256': sha(model), 'interface': interface, 'evaluation_inputs': inputs,
            'evaluation_sha256': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()}


def gpu_device(server, expected):
    """Name of the single visible CUDA device if it matches `expected`, else None.

    CUDA's default ordering differs from nvidia-smi's, so CUDA_VISIBLE_DEVICES=0 picked the
    desktop 4070 here. Force PCI order for this process and every child it starts.
    """
    os.environ['CUDA_DEVICE_ORDER'] = 'PCI_BUS_ID'
    try:
        listing = subprocess.run([str(server), '--list-devices'], capture_output=True, text=True,
                                 timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    names = [line.split(':', 1)[1].split('(')[0].strip() for line in listing.splitlines()
             if line.strip().startswith('CUDA') and ':' in line]
    return names[0] if len(names) == 1 and expected in names[0] else None


def all_executed(path, *, required=None):
    try:
        cases = ET.parse(path).findall('.//testcase')
    except (ET.ParseError, OSError):
        return False
    if not cases or any(c.find(tag) is not None for c in cases for tag in ('skipped', 'failure', 'error')):
        return False
    if required is not None:
        actual = {(c.get('classname'), c.get('name')) for c in cases}
        return len(cases) == len(required) and actual == required
    return True


def evaluation_gate(pin_path=ROOT / 'dev/holdout_manifest.sha256'):
    """Audit every development task against the frozen held-out suite before a model job."""
    from dev.broad_runner import development_rows
    from dev.eval_gate import verify
    try:
        pin = Path(pin_path).read_text().split()[0]
    except (OSError, IndexError):
        return {'ok': False, 'reason': 'held-out suite is not frozen'}
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / 'development.json'
        manifest.write_text(json.dumps(development_rows()))
        return verify(ROOT / 'dev/holdout_manifest.json', pin, manifest)


def execute(directory, stages, *, required_cases=None):
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
        roster = (required_cases or {}).get(name)
        ok = rc == 0 and (all_executed(evidence, required=roster) if evidence else roster is None)
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


def previous_held_out(gguf_sha256, base=ROOT / 'reports' / 'factory', suite='v1'):
    """Earlier held-out jobs of `suite` on these exact model bytes: each suite runs once per
    candidate. Jobs from before suites were recorded are v1."""
    found = []
    for identity in sorted(Path(base).glob('held-out-*/identity.json')):
        try:
            data = json.loads(identity.read_text())
            if data.get('gguf_sha256') == gguf_sha256 and data.get('held_out_suite', 'v1') == suite:
                found.append(identity.parent)
        except (OSError, ValueError):
            found.append(identity.parent)  # unreadable: count it, never silently rerun
    return found


def run_held_out(directory, gguf, server, device, suite='v1', interface=None):
    from dev.holdout_runner import SUITES
    interface = interface or SUITES[suite]['interface']
    identity = {**fast12_identity(gguf, server, extra_sources=SUITES[suite]['sources'], interface=interface),
                'device': device, 'held_out_suite': suite}
    (directory / 'identity.json').write_text(json.dumps(identity, indent=2, sort_keys=True) + '\n')
    return execute(directory, [('held-out', ['.venv/bin/python', '-m', 'dev.holdout_runner',
        server.resolve(), gguf.resolve(), directory, '--suite', suite, '--interface', str(interface)], None)])


def run_development(directory, suite, gguf, server, device, interface=INTERFACE_VERSION):
    if suite == 'broad':
        from dev.broad_runner import SOURCES
        runner, sources = 'dev.broad_runner', SOURCES
    else:
        runner, sources = 'dev.fast12_runner', ()
    identity = {**fast12_identity(gguf, server, extra_sources=sources, interface=interface), 'device': device}
    (directory / 'identity.json').write_text(json.dumps(identity, indent=2, sort_keys=True) + '\n')
    return execute(directory, [('dev-suite', ['.venv/bin/python', '-m', runner,
        server.resolve(), gguf.resolve(), directory, '--interface', str(interface)], None)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', choices=['check', 'trial', 'fast12', 'broad', 'screen', 'pilot', 'audit-splits',
                                        'compare', 'assess', 'held-out', 'margins'])
    parser.add_argument('--run-dir', type=Path, help='assess: completed matched pilot directory')
    parser.add_argument('--pilot', action='append', default=[], metavar='PILOT',
                        help='margins: a completed pilot directory under reports/factory (repeat per seed)')
    parser.add_argument('--stock', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--held-out', type=Path)
    parser.add_argument('--suite', choices=('v1', 'v2', 'v3'), default='v1', help='held-out: which frozen suite')
    parser.add_argument('--interface', type=int, default=None,
                        help="held-out, fast12, broad: interface the model was trained on "
                             "(default: the suite's, or the shipped model's)")
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--held-out-sha256', help='previously pinned digest; never derive from current input')
    parser.add_argument('--gguf', type=Path)
    parser.add_argument('--model', action='append', default=[], metavar='LABEL=GGUF',
                        help='repeat for each local GGUF in a screen')
    parser.add_argument('--reference', help='comparison label for screen (does not select the release reference)')
    parser.add_argument('--base', action='append', default=[], help='pilot base key (repeat): minicpm, qwen08')
    parser.add_argument('--data', type=Path, help='pilot: reuse a built corpus v2 directory (default: build one)')
    parser.add_argument('--max-minutes', type=float, default=25.0, help='pilot: training time box per base')
    parser.add_argument('--minutes', action='append', default=[], metavar='BASE=M',
                        help='pilot: per-base training time box overriding --max-minutes')
    parser.add_argument('--resume', type=Path, help='pilot: continue an interrupted pilot job directory')
    parser.add_argument('--arm', action='append', default=[], metavar='NAME=DATA',
                        help='pilot: matched experiment arms control=DIR then treatment=DIR (replaces --data)')
    parser.add_argument('--max-epochs', type=int, help='pilot: declared training epoch cap per base')
    parser.add_argument('--train-seed', type=int,
                        help='pilot: trainer seed for every base and arm (default: the trainer default, 42)')
    parser.add_argument('--previous', action='append', default=[], metavar='BASE=GGUF@INTERFACE',
                        help='pilot: also score an earlier artifact under its own interface (reference only)')
    parser.add_argument('--lr-schedule', choices=('constant', 'cosine'),
                        help='pilot: learning-rate schedule (default constant; cosine needs --max-epochs)')
    parser.add_argument('--stock-from', type=Path,
                        help='pilot: reuse stock scores from a previous pilot job when artifact and evaluation match')
    parser.add_argument('--server', type=Path, default=Path(os.environ.get('LLAMA_SERVER', Path.home() / 'programs/llama.cpp/build/bin/llama-server')))
    parser.add_argument('--gpu-name', default=os.environ.get('LILGUY_GPU', 'RTX 3090'),
                        help='model jobs run only when exactly one visible CUDA device matches')
    args = parser.parse_args()
    if args.job == 'assess':
        from dev.factory_assess import assess
        if not args.run_dir or len(args.base) != 1:
            parser.error('assess needs --run-dir and one --base')
        try:
            print(assess(args.run_dir, args.base[0]))
        except (OSError, ValueError, KeyError) as exc:
            parser.exit(1, f'Assessment refused: {exc}\n')
        return 0
    device = None
    models = None
    gate = {}
    if args.job == 'compare':
        from dev.fast12_compare import compare
        if not (args.stock and args.candidate):
            parser.error('compare needs --stock and --candidate Fast12 report directories')
        try:
            print(json.dumps(compare(args.stock, args.candidate), sort_keys=True))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            parser.exit(1, f'Cannot compare Fast12 reports: {exc}\n')
        return 0
    if args.job == 'margins':
        # Decision margins at every roster task the round lost (docs/plan/INTERPRETABILITY.md, lesson 5).
        # Needs torch/peft: runs under the training Python, on whatever GPU the caller made visible.
        if not args.pilot:
            parser.error('margins needs at least one --pilot PILOT')
        train_python = os.environ.get('LILGUY_TRAIN_PYTHON', '/home/ivy/Work/chrysopoeia/.venv/bin/python')
        out = Path(tempfile.mkdtemp(prefix='margins-', dir=ROOT / 'reports' / 'factory'))
        print(out, flush=True)
        argv = [train_python, '-m', 'dev.interp.margins', str(out)]
        for pilot in args.pilot:
            argv += ['--candidate', Path(pilot).name]
        return subprocess.run(argv, cwd=ROOT).returncode
    if args.job == 'audit-splits':
        from dev.eval_gate import verify
        if not (args.held_out and args.held_out_sha256 and args.manifest):
            parser.error('audit-splits requires --held-out, --held-out-sha256 and --manifest')
        result = verify(args.held_out, args.held_out_sha256, args.manifest)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['ok'] else 1
    if args.job == 'screen':
        from dev import factory_screen
        if args.gguf or not args.server.is_file():
            parser.error('screen uses --model instead of --gguf and requires a local llama-server')
        try:
            models = factory_screen.parse_models(args.model, args.reference)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    elif args.job == 'pilot':
        from dev.v2_train import BASES
        if args.gguf or not args.server.is_file() or not args.base or set(args.base) - set(BASES) \
                or len(set(args.base)) != len(args.base):
            parser.error(f'pilot needs one or more distinct --base from {sorted(BASES)} and a local llama-server')
    elif args.job != 'check' and not (args.gguf and args.gguf.is_file() and args.server.is_file()):
        parser.error(f'{args.job} needs a local --gguf and llama-server (--server or LLAMA_SERVER)')
    if args.job != 'check':
        gate = evaluation_gate()
        if not gate['ok']:
            parser.exit(1, f"Evaluation gate failed: {gate['reason']}\n")
        if args.job == 'held-out':
            from dev.holdout_runner import suite_gate
            selected_gate = suite_gate(args.suite)
            if not selected_gate['ok']:
                parser.exit(1, f"Selected held-out gate failed: {selected_gate['reason']}\n")
            with args.gguf.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            earlier = previous_held_out(digest, suite=args.suite)
            if earlier:
                parser.exit(1, f'The held-out suite already ran on this model ({earlier[0]}); '
                               'it runs once per candidate.\n')
        device = gpu_device(args.server, args.gpu_name)
        if device is None:
            parser.exit(1, f'Expected exactly one visible CUDA device matching {args.gpu_name!r}; '
                           'set CUDA_VISIBLE_DEVICES (PCI order).\n')
    base = ROOT / 'reports' / 'factory'
    base.mkdir(parents=True, exist_ok=True)
    with (base / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(2, 'Another factory job owns the sandbox gate.\n')
        if args.job == 'pilot' and args.resume:
            directory = args.resume.resolve()
            if directory.parent != base.resolve() or not (directory / 'plan.json').is_file():
                parser.exit(1, 'resume needs an existing pilot job directory under reports/factory\n')
        else:
            directory = Path(tempfile.mkdtemp(prefix=args.job + '-', dir=base))
        print(directory, flush=True)
        if models is not None:
            from dev import factory_screen
            try:
                factory_screen.run(directory, models, args.reference, device, gate,
                    lambda out, suite, gguf: run_development(out, suite, gguf, args.server, device))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                parser.exit(1, f'Screen stopped: {exc}; see {directory}\n')
            print(directory / 'comparison.json', flush=True)
            return 0
        if args.job == 'pilot':
            from dev import factory_pilot
            minutes = {b: float(dict(m.split('=', 1) for m in args.minutes).get(b, args.max_minutes))
                       for b in args.base}
            evaluate = lambda out, suite, gguf, interface: run_development(  # noqa: E731
                out, suite, gguf, args.server, device, interface)
            try:
                previous = factory_pilot.parse_previous(args.previous)
                if args.arm:
                    from dev import v2_report
                    if args.data or args.resume or args.lr_schedule:
                        parser.exit(1, '--arm replaces --data and --lr-schedule and cannot resume\n')
                    arms = factory_pilot.parse_arms(args.arm)
                    factory_pilot.run_arms(directory, arms, args.base, factory_pilot.run, v2_report.compare_base,
                                           server=args.server, device=device, gate=gate,
                                           stock_from=args.stock_from, max_minutes=minutes,
                                           max_epochs=args.max_epochs, evaluate=evaluate,
                                           train_seed=args.train_seed,
                                           control_only={'previous': previous} if previous else None)
                    print(directory / 'arms.json', flush=True)
                    return 0
                factory_pilot.run(directory, bases=args.base, data=args.data, server=args.server, device=device,
                                  gate=gate, stock_from=args.stock_from, max_minutes=minutes,
                                  max_epochs=args.max_epochs, lr_schedule=args.lr_schedule,
                                  train_seed=args.train_seed,
                                  resume=bool(args.resume), evaluate=evaluate, previous=previous)
            except (RuntimeError, ValueError, OSError, KeyError) as exc:
                parser.exit(1, f'Pilot stopped: {exc}; see {directory}\n')
            print(directory / 'comparison.json', flush=True)
            return 0
        if args.job == 'held-out':
            return run_held_out(directory, args.gguf, args.server, device, args.suite, args.interface)
        if args.job in ('fast12', 'broad'):
            return run_development(directory, args.job, args.gguf, args.server, device,
                                   args.interface or INTERFACE_VERSION)
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
                          ('safety-prerequisites', ['.venv/bin/python', '-c',
                              'import shutil, sys; sys.exit(0 if shutil.which("rsync", path="/usr/bin:/bin") '
                              'else "Full v1 safety acceptance requires rsync on the sandbox PATH for corpus case 17.")']),
                          ('v1-bypass-corpus', ['.venv/bin/python', '-m', 'pytest', '-q',
                                                'tests/bypass/test_v1_run_corpus.py']),
                          ('trainer-smoke', ['dev/train_tests.sh'])]:
            if name == 'safety-prerequisites':
                stages.append((name, cmd, None))
                continue
            evidence = directory / f'{name}.xml'
            stages.append((name, [*cmd, f'--junitxml={evidence}'], evidence))
        return execute(directory, stages, required_cases={'v1-bypass-corpus': V1_SAFETY_CASES})


if __name__ == '__main__':
    raise SystemExit(main())
