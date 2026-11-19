"""Calibrate text workflows through the real guarded v1 tools."""
import pytest

from dev import dev_text_workflows as suite, fast12_runner
from lilguy import protocol


@pytest.mark.parametrize('task', suite.TASKS, ids=lambda t: t.id)
def test_text_workflow_controls(tmp_path, task):
    tools = protocol.load_tools()
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, suite.grade)
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, suite.grade)
    for record in (oracle, null):
        assert record['infra_error'] is None, record
        assert record['original_unchanged'] is True
    assert oracle['failures'] == [], oracle
    assert null['failures'], null
