import pytest

from dev.factory_pilot import base_schedules, parse_arms
from dev.v2_train import lr_at


def test_separate_schedules_and_single_base_arms():
    assert base_schedules(['qwen08=linear'], ['minicpm', 'qwen08'], 'cosine') == {
        'minicpm': 'cosine', 'qwen08': 'linear'}
    assert parse_arms(['control=data@cosine', 'treatment=data@linear'])['treatment']['lr_schedule'] == 'linear'


@pytest.mark.parametrize('values', [['other=linear'], ['qwen08=unknown'], ['qwen08=linear'] * 2])
def test_invalid_override(values):
    with pytest.raises(ValueError):
        base_schedules(values, ['qwen08'], None)


def test_decay_shapes_share_warmup_not_tail():
    for schedule in ('linear', 'cosine'):
        assert [lr_at(s, 100, 1., schedule) for s in range(4)] == [1/3, 2/3, 1., 1.]
    assert lr_at(80, 100, 1., 'linear') == pytest.approx(20/97)
    assert lr_at(80, 100, 1., 'cosine') < lr_at(80, 100, 1., 'linear')
