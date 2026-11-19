"""Calibrate the extra decision and artifact fixtures through the guarded v1 runner."""
import pytest

from dev import dev_decisions, fast12_runner
from lilguy import protocol


@pytest.mark.parametrize('task', dev_decisions.TASKS, ids=lambda task: task.id)
def test_decision_controls(tmp_path, task):
    tools = protocol.load_tools()
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, dev_decisions.grade)
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, dev_decisions.grade)
    for record in (oracle, null):
        assert record['infra_error'] is None, record
        assert record['original_unchanged'] is True
    assert oracle['failures'] == [], oracle
    assert null['failures'], null
