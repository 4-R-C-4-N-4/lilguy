import math

import pytest

from dev import decision_diagnose as d


def _decode(ids):
    return ''.join({1: 'tool ', 2: 'fs.read', 3: '\npath: x', 4: 'fs.find', 9: '???'}[i] for i in ids)


def test_teacher_row_requires_complete_decision_not_just_first_token():
    row = d.teacher_record('tool fs.read', [1, 2, 3], [True, True, False], [1, 4, 9],
                           [-0.2, -0.3, -8.0], _decode)
    assert row['teacher_correct'] is False
    assert row['teacher_prediction'] == 'tool fs.find'
    assert row['decision_logprob'] == pytest.approx(-0.5)
    assert math.exp(row['decision_logprob']) == pytest.approx(math.exp(-0.5))


def test_teacher_row_ignores_argument_and_padding_predictions():
    row = d.teacher_record('tool fs.read', [-100, 1, 2, 3], [False, True, True, False],
                           [9, 1, 2, 9], [-9.0, -0.2, -0.3, -8.0], _decode)
    assert row['teacher_correct'] is True
    assert row['teacher_prediction'] == 'tool fs.read'
    assert row['decision_tokens'] == 2


def test_teacher_row_refuses_empty_or_misaligned_decision():
    with pytest.raises(ValueError):
        d.teacher_record('ask', [1], [False], [1], [-0.1], _decode)
    with pytest.raises(ValueError):
        d.teacher_record('ask', [1, 2], [True], [1], [-0.1], _decode)


def test_generated_prediction_is_first_line_not_a_mentioned_tool():
    assert d.generated_class('ask\nShould I run fs.read?') == 'ask'
    assert d.generated_class('I would ask\nWhich file?') == 'invalid'
    assert d.generated_class('tool fs.read\npath: x') == 'tool fs.read'


def test_generation_suffix_never_includes_prompt_tokens():
    assert d.decode_suffix([10, 20, 1, 2, 3], 2, _decode) == 'tool fs.read\npath: x'
    with pytest.raises(ValueError):
        d.decode_suffix([1, 2], 3, _decode)


def test_teacher_rows_feed_the_shared_summary_contract():
    from dev.decision_metrics import summarize
    row = d.teacher_record('tool fs.read', [1, 2], [True, True], [1, 4], [-0.2, -0.3], _decode)
    row['generated'] = 'tool fs.read'
    result = summarize([row])['by_class']['tool fs.read']
    assert result['count'] == 1 and result['decision_accuracy'] == 0 and result['generated_accuracy'] == 1


def _row(behaviour, *actions):
    messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'r'}]
    for action in actions:
        messages += [{'role': 'assistant', 'content': action}, {'role': 'user', 'content': 'obs'}]
    return {'behaviour': behaviour, 'messages': messages[:-1]}


def test_contrast_decision_points_are_first_non_look_actions_of_ask_act_episodes():
    rows = [_row('ask-ambiguous', 'tool fs.find\nname_glob: a*', 'ask\nWhich?'),
            _row('act-unambiguous', 'tool fs.find\nname_glob: a*'),
            _row('act-unambiguous', 'tool fs.find\nname_glob: a*', 'tool fs.edit\npath: a'),
            _row('act-unambiguous', 'tool fs.find\nname_glob: a*', 'tool fs.edit\npath: a', 'done\nok'),
            _row('pending-stop', 'tool fs.list\npath: .', 'run\nrm x')]
    assert d.contrast_decision_points(rows) == [0, 2]


def test_diagnostic_cli_accepts_original_training_corpus_for_membership(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(d, 'run', lambda args: seen.append(args))
    assert d.main([str(tmp_path), str(tmp_path / 'out'), '--base', 'minicpm',
                   '--r1-data', str(tmp_path / 'r1')]) == 0
    assert seen[0].r1_data == tmp_path / 'r1'
