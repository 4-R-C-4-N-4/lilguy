"""Calibrate the append probe under interface 6: scripted solution passes, immediate done fails."""
import pytest

from dev import fast12_runner as fr, focus_append
from lilguy import protocol

pytestmark = pytest.mark.sandbox


@pytest.mark.parametrize('task', focus_append.TASKS, ids=lambda t: t.id)
def test_append_probe_controls(tmp_path, task):
    tools = protocol.load_tools(version=6)
    oracle = fr.run_oracle(tmp_path / 'oracle', task, tools, focus_append.grade, version=6)
    scored = fr.interface_grade(focus_append.grade, answer_required=fr.answer_required(oracle), version=6)
    assert oracle['infra_error'] is None and list(scored(
        task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
        events=fr._events(oracle), original_unchanged=oracle['original_unchanged'])) == [], oracle['changes']
    null = fr.run_false_done(tmp_path / 'null', task, tools, scored, version=6)
    assert null['infra_error'] is None and null['failures']
