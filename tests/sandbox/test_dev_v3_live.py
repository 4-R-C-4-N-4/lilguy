"""Calibrate the whole development roster under interface-v3 grading on fresh guarded fixtures.

For every task, in the mode the model is given (`ask` for the listed questions, `do` otherwise):
the v3 oracle passes with a bare `done`, the answer to a question being the quoted output of its
last command; and an immediate bare `done` fails. Question mode must also refuse real writes:
recorded v2 model steps that wrote files during questions are replayed and come back rejected,
with nothing staged and the originals untouched. No model, no held-out task.
"""
import pytest

from dev import broad_runner, dev_decisions, dev_verification, fast12, fast12_runner as fr
from lilguy import protocol

pytestmark = pytest.mark.sandbox

ROSTER = [(task, fast12.grade) for task in fast12.TASKS] + list(broad_runner.task_graders())


@pytest.mark.parametrize('task,grade', ROSTER, ids=[task.id for task, _ in ROSTER])
def test_v3_controls(tmp_path, task, grade):
    tools = protocol.load_tools()
    task = fr.oracle_for(task, 3)
    mode = fr.task_mode(task, 3)
    oracle = fr.run_oracle(tmp_path / 'oracle', task, tools, grade, version=3, mode=mode)
    assert oracle['infra_error'] is None and oracle['terminal'] == 'done' and oracle['answer'] == ''
    scored = fr.interface_grade(grade, answer_required=fr.answer_required(oracle), version=3)
    failures = list(scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                           events=fr._events(oracle), original_unchanged=oracle['original_unchanged']))
    assert failures == [], (failures, fr.quote_text(fr._events(oracle), task.files))
    null = fr.run_false_done(tmp_path / 'null', task, tools, scored, version=3, mode=mode)
    assert null['infra_error'] is None and null['failures'], null


# Steps v2 adapters actually took on development questions (reports/factory/pilot-zm8ou4p3).
RECORDED_WRITES = [
    (dev_verification, 'summarize_missing_packet_ids',
     ('run\nLC_ALL=C comm -23 <(sort requested.ids) <(sort received.ids) > missing.txt', 'done')),
    (dev_decisions, 'matching_normalized_addresses',
     ("run\nsed 's/[[:space:]]*$//' postcard-a.txt > postcard-a-trim.txt", 'done')),
    (dev_decisions, 'latest_iso_timestamp',
     ('run\ncut -d, -f1 arrivals.tsv > timestamps.tsv\nsort -u timestamps.tsv', 'done')),
]


@pytest.mark.parametrize('module,task_id,steps', RECORDED_WRITES, ids=[t for _, t, _ in RECORDED_WRITES])
def test_question_mode_rejects_recorded_writes(tmp_path, module, task_id, steps):
    tools = protocol.load_tools()
    task = fr.with_oracle(next(t for t in module.TASKS if t.id == task_id), steps)
    assert fr.task_mode(task, 3) == 'ask'
    run = fr.run_oracle(tmp_path / 'ask', task, tools, module.grade, version=3, mode='ask')
    assert run['infra_error'] is None
    assert run['changes'] == {} and run['original_unchanged'] is True
    assert protocol.observation_policy(run['events'][0]['observation']) == 'rejected'
    assert 'policy: rejected (read-only question: ' in run['events'][0]['observation']
    staged = fr.run_oracle(tmp_path / 'do', task, tools, module.grade, version=3, mode='do')
    assert staged['changes'] != {}  # the same step does write in do mode
