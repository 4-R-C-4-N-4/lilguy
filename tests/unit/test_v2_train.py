"""Trainer v2 and pilot-report contracts that need neither torch nor a GPU."""
import random

import pytest

from dev import v2_report, v2_train


def test_decision_span_is_the_action_first_line():
    assert v2_train.decision_chars('run\nls -la') == 3
    assert v2_train.decision_chars('tool fs.read\npath: a.txt') == len('tool fs.read')
    assert v2_train.decision_chars('ask\nWhich file?') == 3
    assert v2_train.decision_chars('done\nChanged x.\nSecond line') == 4
    assert v2_train.decision_chars('tool fs.edit\npath: a\nold <<<\nx\n>>>\nnew: y') == len('tool fs.edit')


def test_token_weights_cover_tokens_overlapping_the_decision():
    offsets = [(0, 2), (2, 4), (4, 5), (5, 9), (9, 12)]  # 'tool' split mid-word, then newline, then args
    assert v2_train.token_weights(offsets, decision_end=4, weight=5) == [5.0, 5.0, 1.0, 1.0, 1.0]
    assert v2_train.token_weights(offsets, decision_end=3, weight=5) == [5.0, 5.0, 1.0, 1.0, 1.0]


def test_batches_respect_budget_cover_every_row_once():
    rng = random.Random(3)
    lengths = [rng.randint(200, 3000) for _ in range(500)]
    batches = v2_train.make_batches(lengths, token_budget=8000, max_batch=8, rng=random.Random(0))
    flat = sorted(i for b in batches for i in b)
    assert flat == list(range(500))
    for b in batches:
        assert len(b) <= 8
        assert len(b) == 1 or max(lengths[i] for i in b) * len(b) <= 8000
    again = v2_train.make_batches(lengths, token_budget=8000, max_batch=8, rng=random.Random(0))
    assert batches == again


def _epoch(decision, token, seconds=60):
    return {'decision_accuracy': decision, 'token_accuracy': token, 'seconds': seconds}


def test_training_length_comes_from_training_fit_or_budget():
    kw = dict(max_epochs=4, fit_decision=0.99, fit_token=0.98, max_seconds=600)
    assert v2_train.stop_reason([_epoch(0.995, 0.985)], elapsed=60, **kw) == 'fit'
    assert v2_train.stop_reason([_epoch(0.995, 0.9)], elapsed=60, **kw) is None
    assert v2_train.stop_reason([_epoch(0.5, 0.5)] * 4, elapsed=240, **kw) == 'max_epochs'
    assert v2_train.stop_reason([_epoch(0.5, 0.5, 300)], elapsed=310, **kw) == 'time_budget'


def test_bases_are_pinned_and_checked(tmp_path):
    assert set(v2_train.BASES) == {'qwen08', 'minicpm'}
    for key, base in v2_train.BASES.items():
        assert base['snapshot'].name == base['revision'] and len(base['revision']) == 40
        assert base['end_token'] == '<|im_end|>' and base['template_kwargs'] == {'enable_thinking': False}
        with pytest.raises(ValueError):
            v2_train.check_base(key, tmp_path)
    with pytest.raises(ValueError):
        v2_train.check_base('other', tmp_path)


def test_verifier_spec_must_name_module_and_function():
    assert v2_train.load_verifier('dev.v2_corpus:verified_rows').__name__ == 'verified_rows'
    with pytest.raises(ValueError):
        v2_train.load_verifier('dev.v2_corpus')


def _side(passed, categories, stops=0, false_done=0):
    return {'evaluation_sha256': {'fast12': 'a', 'broad': 'b'}, 'device': 'RTX 3090', 'passed_tasks': passed,
            'categories': {c: {'passed': p, 'total': 5} for c, p in categories.items()},
            'policy_stops': stops, 'false_done': false_done}


def test_pilot_gate_requires_per_category_gains_and_no_new_unsafe_behaviour(monkeypatch):
    sides = {'stock': _side(['a'], {'ask': 0, 'edit': 1}, stops=2, false_done=4),
             'tuned': _side(['a', 'b'], {'ask': 1, 'edit': 2}, stops=2, false_done=3)}
    monkeypatch.setattr(v2_report, 'side_summary', lambda root: sides[root])
    result = v2_report.compare_base('stock', 'tuned')
    assert result['improved'] == ['b'] and result['regressed'] == []
    assert all(result['gate'].values())
    sides['tuned'] = _side(['b'], {'ask': 1, 'edit': 1}, stops=3, false_done=3)
    gate = v2_report.compare_base('stock', 'tuned')['gate']
    assert not gate['beats_stock_every_category'] and not gate['no_extra_policy_stops']
    sides['tuned'] = {**sides['tuned'], 'device': 'other'}
    with pytest.raises(ValueError):
        v2_report.compare_base('stock', 'tuned')
