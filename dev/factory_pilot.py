"""One-command v2 pilot: verify (or build) the corpus, then per base check template parity, train,
export a matched stock/tuned Q8_0 pair with identical converter flags, score both development
suites for both artifacts, and write comparison.json. Development only; never the held-out suite.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from dev import v2_report

ROOT = Path(__file__).resolve().parents[1]
LLAMA = Path(os.environ.get('LILGUY_LLAMA_CPP', Path.home() / 'programs/llama.cpp'))
LLAMA_REVISION = '01818e4956858fe225a6875aae88b4cbee0b319e'
TRAINER = Path(os.environ.get('LILGUY_TRAIN_PYTHON', Path.home() / 'Work/chrysopoeia/.venv/bin/python'))
MIN_FREE_GIB = 30


def sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Stage:
    """Run one subprocess stage with its own log; record the outcome in the job's plan."""

    def __init__(self, directory, plan):
        self.directory, self.plan = directory, plan

    def __call__(self, name, argv, env=None):
        started = time.monotonic()
        print(name, flush=True)
        with (self.directory / f'{name}.log').open('w') as log:
            rc = subprocess.run([str(a) for a in argv], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                env={**os.environ, **(env or {})}).returncode
        self.plan['stages'].append({'name': name, 'exit': rc, 'seconds': round(time.monotonic() - started, 1)})
        self.save()
        if rc != 0:
            raise RuntimeError(f'stage {name} failed (exit {rc}); see {self.directory}/{name}.log')

    def save(self):
        (self.directory / 'plan.json').write_text(json.dumps(self.plan, indent=2) + '\n')


def preflight():
    if subprocess.check_output(['git', '-C', LLAMA, 'rev-parse', 'HEAD'], text=True).strip() != LLAMA_REVISION:
        raise RuntimeError(f'llama.cpp must be at {LLAMA_REVISION}')
    if subprocess.check_output(['git', '-C', LLAMA, 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise RuntimeError('llama.cpp checkout has local changes')
    if not TRAINER.is_file():
        raise RuntimeError(f'missing training interpreter {TRAINER}')
    free = shutil.disk_usage(ROOT).free / 2**30
    if free < MIN_FREE_GIB:
        raise RuntimeError(f'only {free:.0f} GiB free; the pilot keeps at least {MIN_FREE_GIB} GiB')


def export(stage, name, src, outfile, convert_args):
    stage(name, [TRAINER, LLAMA / 'convert_hf_to_gguf.py', src, *convert_args, '--outtype', 'q8_0',
                 '--outfile', outfile], env={'PYTHONPATH': str(LLAMA / 'gguf-py')})
    return outfile


def train_argv(trainpy, base, snapshot, data, training, minutes, max_epochs, lr_schedule=None):
    argv = [trainpy, 'dev.v2_train', base, snapshot, data, training, '--max-minutes', minutes]
    if max_epochs:
        argv += ['--max-epochs', max_epochs]
    return argv + ['--lr-schedule', lr_schedule] if lr_schedule else argv


def parse_arms(values):
    """`NAME=DATA[@SCHEDULE]` for control then treatment. Arms must differ in exactly one of the
    training corpus or the learning-rate schedule, so the comparison isolates one factor."""
    arms = {}
    for value in values:
        name, _, rest = value.partition('=')
        data, at, schedule = rest.rpartition('@') if '@' in rest else (rest, '', '')
        if at and schedule not in ('constant', 'cosine'):
            raise ValueError(f'unknown schedule in {value!r}')
        arms[name] = {'data': Path(data), **({'lr_schedule': schedule} if at else {})}
    if list(arms) != ['control', 'treatment']:
        raise ValueError('arms must be exactly control then treatment')
    control, treatment = arms.values()
    differences = [key for key in ('data', 'lr_schedule') if control.get(key) != treatment.get(key)]
    if len(differences) != 1:
        raise ValueError(f'arms must differ in exactly one factor, not {differences or "none"}')
    return arms


def run_arms(directory, arms, bases, run_one, compare, control_only=None, **kwargs):
    """A matched control/treatment experiment: identical settings except the training corpus.

    Each arm is a complete pilot job (stock and tuned, both development suites) under
    `directory/<arm>`; afterwards the treatment's tuned artifact is compared with the control's.
    An arm is a data path or a dict of per-arm settings (`data`, optionally `lr_schedule`).
    `control_only` settings (an earlier artifact to re-score) are scored once, in the control arm.
    """
    if list(arms) != ['control', 'treatment']:
        raise ValueError('arms must be exactly control then treatment')
    results = {}
    for arm, spec in arms.items():
        spec = spec if isinstance(spec, dict) else {'data': spec}
        extra = control_only if arm == 'control' and control_only else {}
        (directory / arm).mkdir(parents=True, exist_ok=True)
        results[arm] = run_one(directory / arm, bases=bases, **spec, **extra, **kwargs)
    summary = {'arms': {arm: (str(spec) if not isinstance(spec, dict) else
                              {k: str(v) for k, v in spec.items()}) for arm, spec in arms.items()},
               'treatment_vs_control': {base: compare(directory / 'control' / base / 'tuned',
                                                      directory / 'treatment' / base / 'tuned') for base in bases}}
    (directory / 'arms.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def parse_previous(values):
    """`BASE=GGUF@INTERFACE` (repeatable): an earlier artifact to score on the same roster under
    the interface it was trained for, as a cross-interface reference (not a matched pair)."""
    previous = {}
    for value in values or ():
        base, sep, rest = value.partition('=')
        path, at, interface = rest.rpartition('@')
        if not (sep and at and base and path and interface.isdigit()) or base in previous:
            raise ValueError(f'expected one BASE=GGUF@INTERFACE per base, got {value!r}')
        gguf = Path(path)
        if not gguf.is_file():
            raise ValueError(f'no such GGUF: {gguf}')
        previous[base] = (gguf.resolve(), int(interface))
    return previous


def reusable_stock(previous, base, gguf, server, device, interface=1):
    """A previous job's stock scores count only if the artifact, evaluation inputs and device match."""
    from dev.broad_runner import SOURCES
    from dev.factory import fast12_identity
    if previous is None:
        return None
    root = Path(previous) / base / 'stock'
    try:
        for suite, sources in (('fast12', ()), ('broad', SOURCES)):
            old = json.loads((root / suite / 'identity.json').read_text())
            now = fast12_identity(gguf, server, extra_sources=sources, interface=interface)
            if (old['gguf_sha256'], old['evaluation_sha256'], old['device']) != (
                    now['gguf_sha256'], now['evaluation_sha256'], device):
                return None
    except (OSError, ValueError, KeyError):
        return None
    return root


def run(directory, *, bases, data, server, device, gate, evaluate, max_minutes, stock_from=None, build_seed=None,
        resume=False, max_epochs=None, previous=None, lr_schedule=None):
    """With `resume`, stages whose outputs already exist in `directory` are kept, not repeated."""
    from dev import v2_train
    preflight()
    old = json.loads((directory / 'plan.json').read_text()) if resume and (directory / 'plan.json').is_file() else {}
    plan = {'job': 'pilot-v2', 'bases': bases, 'device': device, 'split_gate': gate, 'max_minutes': max_minutes,
            'max_epochs': max_epochs, 'lr_schedule': lr_schedule or 'constant',
            'llama_cpp': LLAMA_REVISION, 'stages': old.get('stages', []),
            'resumed': bool(resume)}
    stage = Stage(directory, plan)
    if data is None:
        data = directory / 'data'
        argv = ['.venv/bin/python', '-m', 'dev.v2_corpus', data]
        if build_seed is not None:
            argv += ['--seed', build_seed]
        stage('corpus', argv)
    data = Path(data).resolve()
    stage('corpus-verify', ['.venv/bin/python', '-c', 'import sys; from dev import v2_corpus; '
                            'print(len(v2_corpus.verified_rows(sys.argv[1])))', data])
    plan['data'] = {'path': str(data), 'train_sha256': sha256(data / 'train.jsonl'),
                    'effects_sha256': sha256(data / 'effects.json'),
                    'datacard': json.loads((data / 'datacard.json').read_text())['stages']}
    interface = json.loads((data / 'meta.json').read_text())['interface']
    plan['interface'] = interface
    stage.save()
    trainpy = ROOT / 'dev/trainpy.sh'
    for base in bases:
        spec = v2_train.BASES[base]
        out = directory / base
        out.mkdir(exist_ok=resume)
        stock_gguf = out / 'stock-q8_0.gguf'
        if not (resume and stock_gguf.is_file()):
            export(stage, f'{base}-export-stock', spec['snapshot'], stock_gguf, spec['convert_args'])
        parity = out / 'parity/template-parity.json'
        if not (resume and parity.is_file() and json.loads(parity.read_text())['ok']):
            stage(f'{base}-template-parity', [trainpy, 'dev.v2_template_check', base, spec['snapshot'], stock_gguf,
                                              server, data, out / 'parity'])
        training = out / 'training'
        if resume and (training / 'adapter/adapter_config.json').is_file() and not (training / 'train-report.json').is_file():
            stage(f'{base}-merge-resume', [trainpy, 'dev.v2_train', base, spec['snapshot'], data, training,
                                           '--merge-only-from-log', directory / f'{base}-train.log'])
        if not (resume and (training / 'train-report.json').is_file()):
            minutes = max_minutes[base] if isinstance(max_minutes, dict) else max_minutes
            stage(f'{base}-train', train_argv(trainpy, base, spec['snapshot'], data, training, minutes, max_epochs,
                                              lr_schedule))
        tuned_gguf = out / 'tuned-q8_0.gguf'
        if not (resume and tuned_gguf.is_file()):
            export(stage, f'{base}-export-tuned', training / 'merged', tuned_gguf, spec['convert_args'])
        plan.setdefault('artifacts', {})[base] = {'stock_q8_0_sha256': sha256(stock_gguf),
                                                  'tuned_q8_0_sha256': sha256(tuned_gguf),
                                                  'convert_args': spec['convert_args']}
        stage.save()
        reused = reusable_stock(stock_from, base, stock_gguf, server, device, interface)
        sides = (('tuned', tuned_gguf),) if reused else (('stock', stock_gguf), ('tuned', tuned_gguf))
        sides = tuple((side, gguf, interface) for side, gguf in sides)
        if reused:
            shutil.copytree(reused, out / 'stock', symlinks=True)
            plan['artifacts'][base]['stock_scores_reused_from'] = str(reused)
        if previous and base in previous:
            earlier, earlier_interface = previous[base]
            sides += (('previous', earlier, earlier_interface),)
            plan['artifacts'][base]['previous'] = {'gguf': str(earlier), 'sha256': sha256(earlier),
                                                   'interface': earlier_interface}
            stage.save()
        for side, gguf, side_interface in sides:
            for suite in ('fast12', 'broad'):
                folder = out / side / suite
                if resume and (folder / f'{suite}.json').is_file():
                    continue
                if folder.exists():
                    shutil.rmtree(folder)
                folder.mkdir(parents=True)
                print(f'{base}: {side} {suite}', flush=True)
                started = time.monotonic()
                rc = evaluate(folder, suite, gguf, side_interface)
                plan['stages'].append({'name': f'{base}-{side}-{suite}', 'exit': rc,
                                       'seconds': round(time.monotonic() - started, 1)})
                stage.save()
    result = v2_report.write(directory, bases)
    plan['status'] = 'passed'
    stage.save()
    return result
