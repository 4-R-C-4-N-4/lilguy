"""Interface v7 live: roster and append-probe controls, and fs.append through the guarded server."""
import pytest

from dev import broad_runner, dev_focus, fast12, fast12_runner as fr, focus_append
from dev.dev_workspace import Task, grade as workspace_grade
from lilguy import protocol

pytestmark = pytest.mark.sandbox
V = 7
ROSTER = [(task, fast12.grade, None, None) for task in fast12.TASKS] + \
    [(task, grade, None, None) for task, grade in broad_runner.task_graders()] + \
    [(task, dev_focus.grade, dev_focus.ASK, dev_focus.ORACLES) for task in dev_focus.TASKS] + \
    [(task, focus_append.grade, None, None) for task in focus_append.TASKS]


@pytest.mark.parametrize('task,grade,ask_ids,oracles', ROSTER, ids=[row[0].id for row in ROSTER])
def test_v7_controls(tmp_path, task, grade, ask_ids, oracles):
    tools = protocol.load_tools(version=V)
    task = fr.oracle_for(task, V, oracles)
    mode = fr.task_mode(task, V, ask_ids)
    oracle = fr.run_oracle(tmp_path / 'oracle', task, tools, grade, version=V, mode=mode)
    assert oracle['infra_error'] is None and oracle['terminal'] == 'done' and oracle['answer'] == ''
    scored = fr.interface_grade(grade, answer_required=fr.answer_required(oracle), version=V)
    failures = list(scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                           events=fr._events(oracle), original_unchanged=oracle['original_unchanged']))
    assert failures == [], (failures, fr.quote_text(fr._events(oracle), task.files))
    null = fr.run_false_done(tmp_path / 'null', task, tools, scored, version=V, mode=mode)
    assert null['infra_error'] is None and null['failures'], null


@pytest.mark.parametrize('before', ['files=1024', 'files=1024\n'])
def test_fs_append_through_the_server(tmp_path, before):
    task = Task('v7_append', 'Add two limits.', {'limits.ini': before},
                ('tool fs.append\npath: limits.ini\nlines <<<\nprocs=512\nalias gs=\'git status\'\n>>>', 'done'),
                {'limits.ini': "files=1024\nprocs=512\nalias gs='git status'\n"})
    record = fr.run_oracle(tmp_path / 'o', task, protocol.load_tools(version=V), workspace_grade, version=V)
    assert record['infra_error'] is None and record['failures'] == [], record
    assert 'appended 2 lines to limits.ini' in record['events'][-1]['observation']
