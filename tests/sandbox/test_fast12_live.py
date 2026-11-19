"""Calibrate every Fast12 task on fresh guarded fixtures: the oracle passes, an immediate false
`done` fails, the original stays unchanged. No model and no held-out tasks."""
import pytest

from dev import fast12, fast12_runner
from lilguy import protocol

pytestmark = pytest.mark.sandbox


@pytest.mark.parametrize('task', fast12.TASKS, ids=lambda task: task.id)
def test_fast12_task_controls(tmp_path, task):
    tools = protocol.load_tools()
    good = fast12_runner.run_oracle(tmp_path / 'good', task, tools, fast12.grade)
    false = fast12_runner.run_false_done(tmp_path / 'false', task, tools, fast12.grade)
    for record in (good, false):
        assert record['original_unchanged'] is True
        assert record['infra_error'] is None, record['infra_error']
    assert good['failures'] == [], good
    assert false['failures'], false
