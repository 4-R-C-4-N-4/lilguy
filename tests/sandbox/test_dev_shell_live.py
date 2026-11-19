"""Calibrate only the new development fixtures, using guarded v1 and no model."""
import pytest

from dev import dev_shell, fast12_runner
from lilguy import protocol


@pytest.mark.parametrize('task', dev_shell.TASKS, ids=lambda task: task.id)
def test_dev_shell_controls(tmp_path, task):
    tools = protocol.load_tools()
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, dev_shell.grade)
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, dev_shell.grade)
    for record in (oracle, null):
        assert record['infra_error'] is None, record
        assert record['original_unchanged'] is True
    assert oracle['failures'] == [], oracle
    assert null['failures'], null
