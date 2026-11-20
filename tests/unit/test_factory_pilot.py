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
