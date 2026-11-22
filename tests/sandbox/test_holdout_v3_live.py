"""Calibrate the frozen held-out suite under interface-v3 grading (no model is run).

Gate from the roadmap: the scripted oracle passes 100% and an immediate false `done` passes 0%,
in the mode each task is issued in. The held-out tasks are never used for tuning or failure
analysis; this only checks the graders.
"""
import pytest

from dev import fast12_runner, holdout_corpus, holdout_v3
from lilguy import protocol

pytestmark = pytest.mark.sandbox


def test_v3_tables_only_name_held_out_tasks():
    ids = {task.id for task in holdout_corpus.TASKS}
    assert holdout_v3.ASK <= ids and set(holdout_v3.ORACLES) <= ids
    assert len(holdout_v3.ASK) == 10 and set(holdout_v3.ORACLES) == holdout_v3.ASK


@pytest.mark.parametrize('task', holdout_corpus.TASKS, ids=lambda task: task.id)
def test_holdout_v3_controls(tmp_path, task):
    tools = protocol.load_tools()
    task = fast12_runner.oracle_for(task, 3, holdout_v3.ORACLES)
    mode = fast12_runner.task_mode(task, 3, holdout_v3.ASK)
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, holdout_corpus.grade,
                                      version=3, mode=mode)
    assert oracle['infra_error'] is None and oracle['original_unchanged'] is True, oracle
    scored = fast12_runner.interface_grade(holdout_corpus.grade,
                                           answer_required=fast12_runner.answer_required(oracle), version=3)
    failures = scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                      events=fast12_runner._events(oracle), original_unchanged=oracle['original_unchanged'])
    assert failures == [], (failures, oracle)
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, scored, version=3, mode=mode)
    assert null['infra_error'] is None and null['failures'], null
