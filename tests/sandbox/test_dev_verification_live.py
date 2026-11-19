"""Calibrate verification tasks through the live guarded v1 runner."""
import pytest

from dev import dev_verification as suite, fast12_runner
from lilguy import protocol


@pytest.mark.parametrize('task', suite.TASKS, ids=lambda task: task.id)
def test_verification_controls(tmp_path, task):
    tools = protocol.load_tools()
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, suite.grade)
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, suite.grade)
    for record in (oracle, null):
        assert record['infra_error'] is None, record
        assert record['original_unchanged'] is True
    assert not oracle['failures'], oracle
    assert null['failures'], null
