"""Calibrate the re-frozen held-out suite under interface-v2 grading (no model is run).

Gate from the roadmap: the scripted oracle passes 100% and an immediate false `done` passes 0%.
The held-out tasks are never used for tuning or failure analysis; this only checks the graders.
"""
import pytest

from dev import fast12_runner, holdout_corpus
from lilguy import protocol

pytestmark = pytest.mark.sandbox


@pytest.mark.parametrize('task', holdout_corpus.TASKS, ids=lambda task: task.id)
def test_holdout_v2_controls(tmp_path, task):
    tools = protocol.load_tools()
    grade = holdout_corpus.grade
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, grade)
    assert oracle['infra_error'] is None and oracle['failures'] == [], oracle
    assert oracle['original_unchanged'] is True
    scored = fast12_runner.interface_grade(grade, answer_required=fast12_runner.answer_required(oracle), version=2)
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, scored)
    assert null['infra_error'] is None and null['failures'], null
