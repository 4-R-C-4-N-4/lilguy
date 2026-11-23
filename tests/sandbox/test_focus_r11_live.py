"""Calibrate the round-11 focus fixtures under interfaces 3 and 4: oracle passes, immediate done fails."""
import pytest

from dev import focus_r11, fast12_runner
from lilguy import protocol


pytestmark = pytest.mark.sandbox


@pytest.mark.parametrize('version', (3, 4))
@pytest.mark.parametrize('task', focus_r11.TASKS, ids=lambda task: task.id)
def test_focus_r11_controls(tmp_path, task, version):
    tools = protocol.load_tools()
    task = fast12_runner.oracle_for(task, version, focus_r11.ORACLES)
    mode = fast12_runner.task_mode(task, version, focus_r11.ASK)
    oracle = fast12_runner.run_oracle(tmp_path / 'oracle', task, tools, focus_r11.grade, version=version, mode=mode)
    assert oracle['infra_error'] is None and oracle['original_unchanged'] is True, oracle
    scored = fast12_runner.interface_grade(focus_r11.grade, answer_required=fast12_runner.answer_required(oracle),
                                           version=version)
    failures = scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                      events=fast12_runner._events(oracle), original_unchanged=oracle['original_unchanged'])
    assert failures == [], (failures, oracle)
    null = fast12_runner.run_false_done(tmp_path / 'null', task, tools, scored, version=version, mode=mode)
    assert null['infra_error'] is None and null['failures'], null
