"""Suite v3 calibration only: real sandbox, no model or inference server."""
import pytest

from dev import fast12_runner, holdout_suite_v3
from lilguy import protocol

pytestmark = pytest.mark.sandbox


@pytest.mark.parametrize('task', holdout_suite_v3.TASKS, ids=lambda task: task.id)
def test_holdout_suite_v3_controls(tmp_path, task):
    tools = protocol.load_tools()
    mode = fast12_runner.task_mode(task, 4, holdout_suite_v3.ASK)
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, holdout_suite_v3.grade,
                                     version=4, mode=mode)
    assert oracle['infra_error'] is None and oracle['original_unchanged'] is True, oracle
    scored = fast12_runner.interface_grade(holdout_suite_v3.grade,
        answer_required=fast12_runner.answer_required(oracle), version=4)
    failures = scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                      events=fast12_runner._events(oracle), original_unchanged=oracle['original_unchanged'])
    assert failures == [], (failures, oracle['changes'])
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, scored, version=4, mode=mode)
    assert null['infra_error'] is None and null['original_unchanged'] is True and null['failures'], null
