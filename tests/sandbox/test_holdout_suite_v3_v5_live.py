"""Held-out suite v3 under interface v5: controls only, no model.

The frozen control test (test_holdout_suite_v3_controls_live.py) is pinned at interface 4 by the
freeze. A candidate trained on v5 runs this suite on v5, so the same oracle and false-done
controls must hold there too, before any model sees the suite. Tasks, files and grader are the
frozen ones; nothing here derives from a model run.
"""
import pytest

from dev import fast12_runner, holdout_suite_v3
from lilguy import protocol

pytestmark = pytest.mark.sandbox


@pytest.mark.parametrize('task', holdout_suite_v3.TASKS, ids=lambda task: task.id)
def test_holdout_suite_v3_controls_v5(tmp_path, task):
    tools = protocol.load_tools()
    mode = fast12_runner.task_mode(task, 5, holdout_suite_v3.ASK)
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, holdout_suite_v3.grade, version=5, mode=mode)
    assert oracle['infra_error'] is None and oracle['original_unchanged'] is True, oracle
    scored = fast12_runner.interface_grade(holdout_suite_v3.grade,
        answer_required=fast12_runner.answer_required(oracle), version=5)
    failures = scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                      events=fast12_runner._events(oracle), original_unchanged=oracle['original_unchanged'])
    assert failures == [], (failures, oracle['changes'])
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, scored, version=5, mode=mode)
    assert null['infra_error'] is None and null['original_unchanged'] is True and null['failures'], null
