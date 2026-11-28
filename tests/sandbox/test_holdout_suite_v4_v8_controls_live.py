"""Held-out suite v4 calibration at interface 8: controls only (the frozen file covers interface 6), no model.

The scripted solution must pass and an immediate `done` must fail for every task, before the
suite is frozen and before any model sees it.
"""
import pytest

from dev import fast12_runner, holdout_suite_v4
from lilguy import protocol

pytestmark = pytest.mark.sandbox
V = 8


@pytest.mark.parametrize('task', holdout_suite_v4.TASKS, ids=lambda task: task.id)
def test_holdout_suite_v4_controls(tmp_path, task):
    tools = protocol.load_tools(version=V)
    mode = fast12_runner.task_mode(task, V, holdout_suite_v4.ASK)
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, holdout_suite_v4.grade, version=V, mode=mode)
    assert oracle['infra_error'] is None and oracle['original_unchanged'] is True, oracle
    scored = fast12_runner.interface_grade(holdout_suite_v4.grade,
        answer_required=fast12_runner.answer_required(oracle), version=V)
    failures = scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                      events=fast12_runner._events(oracle), original_unchanged=oracle['original_unchanged'])
    assert failures == [], (failures, oracle['changes'])
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, scored, version=V, mode=mode)
    assert null['infra_error'] is None and null['original_unchanged'] is True and null['failures'], null
