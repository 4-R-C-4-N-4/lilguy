"""Factory pilot control/treatment orchestration contracts (no GPU, no sandbox)."""
import json
from pathlib import Path

import pytest

from dev import factory_pilot


def test_train_stage_declares_time_box_and_optional_epoch_cap():
    argv = factory_pilot.train_argv('t.sh', 'minicpm', Path('/snap'), Path('/data'), Path('/out'), 35.0, None)
    assert argv == ['t.sh', 'dev.v2_train', 'minicpm', Path('/snap'), Path('/data'), Path('/out'),
                    '--max-minutes', 35.0]
    capped = factory_pilot.train_argv('t.sh', 'qwen08', Path('/snap'), Path('/data'), Path('/out'), 30.0, 1)
    assert capped[-2:] == ['--max-epochs', 1]
    cosine = factory_pilot.train_argv('t.sh', 'qwen08', Path('/snap'), Path('/data'), Path('/out'), 30.0, 1,
                                      'cosine')
    assert cosine[-4:] == ['--max-epochs', 1, '--lr-schedule', 'cosine']
    seeded = factory_pilot.train_argv('t.sh', 'qwen08', Path('/snap'), Path('/data'), Path('/out'), 30.0, 1,
                                      'cosine', seed=43)
    assert seeded[-6:] == ['--max-epochs', 1, '--lr-schedule', 'cosine', '--seed', 43]
    assert '--seed' not in cosine  # default keeps the trainer's recorded seed (42)


def test_arms_run_in_order_with_identical_settings_except_data(tmp_path):
    calls = []

    def run_one(directory, *, data, **kwargs):
        calls.append((directory, data, kwargs))
        return {'bases': {}}

    compared = []

    def compare(control, treatment):
        compared.append((control, treatment))
        return {'gate': {}, 'improved': ['x'], 'regressed': []}

    result = factory_pilot.run_arms(tmp_path, {'control': Path('/c'), 'treatment': Path('/t')}, ['minicpm'],
                                    run_one, compare, server='s', max_epochs=1)
    assert [(c[0].name, c[1]) for c in calls] == [('control', Path('/c')), ('treatment', Path('/t'))]
    assert calls[0][2] == calls[1][2] == {'bases': ['minicpm'], 'server': 's', 'max_epochs': 1}
    assert compared == [(tmp_path / 'control/minicpm/tuned', tmp_path / 'treatment/minicpm/tuned')]
    saved = json.loads((tmp_path / 'arms.json').read_text())
    assert saved == result and saved['arms'] == {'control': '/c', 'treatment': '/t'}
    assert saved['treatment_vs_control']['minicpm']['improved'] == ['x']


def test_arms_require_exactly_control_and_treatment(tmp_path):
    with pytest.raises(ValueError):
        factory_pilot.run_arms(tmp_path, {'control': Path('/c')}, ['minicpm'], None, None)
    with pytest.raises(ValueError):
        factory_pilot.run_arms(tmp_path, {'a': Path('/c'), 'b': Path('/t')}, ['minicpm'], None, None)


def test_arm_specs_can_differ_only_by_schedule_and_previous_goes_to_control(tmp_path):
    arms = factory_pilot.parse_arms(['control=/d@constant', 'treatment=/d@cosine'])
    assert arms == {'control': {'data': Path('/d'), 'lr_schedule': 'constant'},
                    'treatment': {'data': Path('/d'), 'lr_schedule': 'cosine'}}
    assert factory_pilot.parse_arms(['control=/c', 'treatment=/t'])['treatment'] == {'data': Path('/t')}
    for bad in (['control=/d@linear', 'treatment=/d'], ['control=/d', 'treatment=/d']):
        with pytest.raises(ValueError):
            factory_pilot.parse_arms(bad)
    calls = []

    def run_one(directory, **kwargs):
        calls.append((directory.name, kwargs))

    factory_pilot.run_arms(tmp_path, arms, ['qwen08'], run_one, lambda c, t: {}, server='s', max_epochs=1,
                           control_only={'previous': {'qwen08': ('/old.gguf', 2)}})
    control, treatment = (kwargs for _, kwargs in calls)
    assert control.pop('previous') and 'previous' not in treatment
    assert control.pop('lr_schedule') == 'constant' and treatment.pop('lr_schedule') == 'cosine'
    assert control == treatment


def test_previous_artifacts_name_their_base_and_interface(tmp_path):
    gguf = tmp_path / 'old.gguf'
    gguf.write_bytes(b'x')
    assert factory_pilot.parse_previous([f'minicpm={gguf}@1']) == {'minicpm': (gguf.resolve(), 1)}
    for bad in (f'minicpm={gguf}', f'={gguf}@1', f'minicpm={tmp_path / "missing.gguf"}@1', f'minicpm={gguf}@v1'):
        with pytest.raises(ValueError):
            factory_pilot.parse_previous([bad])
    with pytest.raises(ValueError):
        factory_pilot.parse_previous([f'minicpm={gguf}@1', f'minicpm={gguf}@2'])


def test_cross_interface_reference_is_reported_but_never_a_gate(monkeypatch):
    from dev import v2_report

    def side(passed, interface, evaluation):
        cats = {'edit': {'passed': len(passed), 'total': 3}}
        return {'passed_tasks': passed, 'device': 'RTX 3090', 'interface': interface,
                'evaluation_sha256': evaluation, 'categories': cats, 'passed': len(passed), 'total': 3}
    monkeypatch.setattr(v2_report, 'side_summary', lambda root: side(['a'], 1, {'fast12': 'old'}))
    ref = v2_report.compare_previous(side(['a', 'b'], 2, {'fast12': 'new'}), Path('/prev'))
    assert ref['cross_interface'] and not ref['same_evaluation']
    assert ref['improved'] == ['b'] and ref['regressed'] == [] and 'gate' not in ref
    assert ref['per_category'] == {'edit': {'previous': 1, 'tuned': 2, 'total': 3}}
