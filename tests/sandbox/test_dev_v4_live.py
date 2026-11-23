"""Calibrate the 80-task development roster and the v4 focus fixtures under interface v4.

Same gate as v3 (tests/sandbox/test_dev_v3_live.py): in the mode the model is given, the
scripted solution passes with a bare `done` and an immediate bare `done` fails. Observations
now frame output unindented, so this also proves every grader reads the v4 format.
"""
import pytest

from dev import broad_runner, dev_focus, fast12, fast12_runner as fr
from lilguy import protocol

pytestmark = pytest.mark.sandbox

ROSTER = [(task, fast12.grade, None, None) for task in fast12.TASKS] + \
    [(task, grade, None, None) for task, grade in broad_runner.task_graders()] + \
    [(task, dev_focus.grade, dev_focus.ASK, dev_focus.ORACLES) for task in dev_focus.TASKS]


@pytest.mark.parametrize('task,grade,ask_ids,oracles', ROSTER, ids=[row[0].id for row in ROSTER])
def test_v4_controls(tmp_path, task, grade, ask_ids, oracles):
    tools = protocol.load_tools()
    task = fr.oracle_for(task, 4, oracles)
    mode = fr.task_mode(task, 4, ask_ids)
    oracle = fr.run_oracle(tmp_path / 'oracle', task, tools, grade, version=4, mode=mode)
    assert oracle['infra_error'] is None and oracle['terminal'] == 'done' and oracle['answer'] == ''
    assert all('<<<' in e['observation'] for e in oracle['events'] if 'stdout (' in e['observation'])
    scored = fr.interface_grade(grade, answer_required=fr.answer_required(oracle), version=4)
    failures = list(scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                           events=fr._events(oracle), original_unchanged=oracle['original_unchanged']))
    assert failures == [], (failures, fr.quote_text(fr._events(oracle), task.files))
    null = fr.run_false_done(tmp_path / 'null', task, tools, scored, version=4, mode=mode)
    assert null['infra_error'] is None and null['failures'], null
