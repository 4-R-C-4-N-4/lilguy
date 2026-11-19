"""Calibrate broader development tasks on fresh guarded fixtures; no model or holdout."""
import pytest

from dev import broad_dev, fast12_runner
from lilguy import protocol


@pytest.mark.parametrize('task', broad_dev.TASKS, ids=lambda task: task.id)
def test_broad_task_controls(tmp_path, task):
    tools = protocol.load_tools()
    good = fast12_runner.run_oracle(tmp_path / 'good', task, tools, broad_dev.grade)
    false = fast12_runner.run_false_done(tmp_path / 'false', task, tools, broad_dev.grade)
    for record in (good, false):
        assert record['original_unchanged'] is True
        assert record['infra_error'] is None, record['infra_error']
    assert good['failures'] == [], good
    assert false['failures'], false
