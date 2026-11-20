"""Calibrate the whole development roster under interface-v2 grading on fresh guarded fixtures.

For every task: the scripted oracle passes; where no answer is the deliverable, the same oracle
ending in a bare `done` also passes; and an immediate false `done` still fails, so dropping
answer-wording checks never lets a do-nothing trajectory through. No model, no held-out task.
"""
import pytest

from dev import broad_runner, fast12, fast12_runner
from lilguy import protocol

pytestmark = pytest.mark.sandbox

ROSTER = [(task, fast12.grade) for task in fast12.TASKS] + list(broad_runner.task_graders())


@pytest.mark.parametrize('task,grade', ROSTER, ids=[task.id for task, _ in ROSTER])
def test_v2_controls(tmp_path, task, grade):
    tools = protocol.load_tools()
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, grade)
    assert oracle['infra_error'] is None and oracle['failures'] == [], oracle
    required = fast12_runner.answer_required(oracle)
    scored = fast12_runner.interface_grade(grade, answer_required=required, version=2)
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, scored)
    assert null['infra_error'] is None and null['failures'], null
    if not required and task.oracle[-1].startswith('done'):
        bare = type(task)(**{**task.__dict__, 'oracle': (*task.oracle[:-1], 'done')})
        terse = fast12_runner.run_oracle(tmp_path / 'bare', bare, tools, scored)
        assert terse['infra_error'] is None and terse['failures'] == [], terse
        assert terse['original_unchanged'] is True
