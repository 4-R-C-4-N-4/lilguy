"""Held-out job plumbing: one run per model, v3 tables, ask-text grading and the summary."""
import json

from dev import factory, fast12_runner, holdout_runner, holdout_v3
from dev.holdout_corpus import TASKS


def test_previous_held_out_finds_runs_on_the_same_bytes(tmp_path):
    (tmp_path / 'held-out-a').mkdir()
    (tmp_path / 'held-out-a' / 'identity.json').write_text(json.dumps({'gguf_sha256': 'abc'}))
    (tmp_path / 'held-out-b').mkdir()
    (tmp_path / 'held-out-b' / 'identity.json').write_text(json.dumps({'gguf_sha256': 'other'}))
    assert factory.previous_held_out('abc', tmp_path) == [tmp_path / 'held-out-a']
    assert factory.previous_held_out('new', tmp_path) == []


def test_unreadable_previous_identity_blocks_a_rerun(tmp_path):
    (tmp_path / 'held-out-x').mkdir()
    (tmp_path / 'held-out-x' / 'identity.json').write_text('{not json')
    assert factory.previous_held_out('anything', tmp_path) == [tmp_path / 'held-out-x']


def test_v3_tables_put_only_family_g_in_ask_mode():
    modes = {t.id: fast12_runner.task_mode(t, 3, holdout_v3.ASK) for t in TASKS}
    assert {i for i, m in modes.items() if m == 'ask'} == {t.id for t in TASKS if '_g_' in t.id}
    assert fast12_runner.task_mode(TASKS[0], 3) == 'do'  # default tables stay the development ones


def test_v3_grading_keeps_ask_text_and_quotes_everything_else():
    seen = []

    def grade(task, *, terminal, answer, changes, events, original_unchanged):
        seen.append(answer)
        return []
    scored = fast12_runner.interface_grade(grade, answer_required=True, version=3)
    kwargs = dict(changes={}, events=[], original_unchanged=True)
    scored(TASKS[0], terminal='ask', answer='x.md is missing', **kwargs)
    scored(TASKS[0], terminal='done', answer='model words', **kwargs)
    assert seen == ['x.md is missing', '']


def _verdict(task, passed, terminal='done', unchanged=True, infra=False):
    return {'task': task, 'passed': passed, 'infra_failure': infra, 'mode': 'do',
            'model_miss': not passed and not infra,
            'model': {'terminal': terminal, 'original_unchanged': unchanged}}


def test_summary_against_scope_targets():
    verdicts = [_verdict(f'holdout_a_x_{i:02d}', i < 8) for i in range(10)]
    summary = holdout_runner.summarize(verdicts)
    assert summary['passed'] == 8 and summary['rate'] == 0.8
    assert summary['families']['a update_setting_value'] == {'passed': 8, 'total': 10}
    assert summary['scope'] == {'completion_target': 0.7, 'completion_met': True, 'zero_destructive_met': True}
    assert summary['done_on_miss'] == 2
    worse = holdout_runner.summarize(verdicts[:5] + [_verdict('holdout_b_y_00', False, unchanged=False)])
    assert worse['workspace_changed_without_commit'] == ['holdout_b_y_00']
    assert worse['scope']['zero_destructive_met'] is False


def test_held_out_v2_is_frozen_and_complete():
    from dev import holdout_v2
    holdout_runner.check_frozen('v2')
    holdout_runner.check_frozen('v1')
    assert len(holdout_v2.TASKS) == 100 and len(holdout_v2.ASK) == 20
    assert {t.id.split('_')[1] for t in holdout_v2.TASKS} == set(holdout_v2.FAMILIES)


def test_one_run_per_suite_and_model(tmp_path):
    (tmp_path / 'held-out-a').mkdir()
    (tmp_path / 'held-out-a' / 'identity.json').write_text(json.dumps({'gguf_sha256': 'abc'}))  # pre-suite: v1
    assert factory.previous_held_out('abc', tmp_path, suite='v1') == [tmp_path / 'held-out-a']
    assert factory.previous_held_out('abc', tmp_path, suite='v2') == []
