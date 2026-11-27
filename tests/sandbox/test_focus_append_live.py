"""Calibrate the append probe under the comparison interfaces: oracle passes, false done fails."""
import pytest

from dev import fast12_runner as fr, focus_append
from lilguy import protocol

pytestmark = pytest.mark.sandbox


@pytest.mark.parametrize('version', (4, 6, 7))
@pytest.mark.parametrize('task', focus_append.TASKS, ids=lambda t: t.id)
def test_append_probe_controls(tmp_path, task, version):
    tools = protocol.load_tools(version=version)
    oracle = fr.run_oracle(tmp_path / 'oracle', task, tools, focus_append.grade, version=version)
    scored = fr.interface_grade(focus_append.grade, answer_required=fr.answer_required(oracle), version=version)
    assert oracle['infra_error'] is None and list(scored(
        task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
        events=fr._events(oracle), original_unchanged=oracle['original_unchanged'])) == [], oracle['changes']
    null = fr.run_false_done(tmp_path / 'null', task, tools, scored, version=version)
    assert null['infra_error'] is None and null['failures']
