"""Calibrate the v4 focus fixtures under interface v3: oracle passes, immediate done fails."""
import pytest

from dev import dev_focus, fast12_runner
from lilguy import protocol


@pytest.mark.parametrize('task', dev_focus.TASKS, ids=lambda task: task.id)
def test_focus_controls(tmp_path, task):
    tools = protocol.load_tools()
    task = fast12_runner.oracle_for(task, 3, dev_focus.ORACLES)
    mode = fast12_runner.task_mode(task, 3, dev_focus.ASK)
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, dev_focus.grade, version=3, mode=mode)
    assert oracle['infra_error'] is None and oracle['original_unchanged'] is True, oracle
    scored = fast12_runner.interface_grade(dev_focus.grade, answer_required=fast12_runner.answer_required(oracle),
                                           version=3)
    failures = scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                      events=fast12_runner._events(oracle), original_unchanged=oracle['original_unchanged'])
    assert failures == [], (failures, oracle)
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, scored, version=3, mode=mode)
    assert null['infra_error'] is None and null['failures'], null
