"""Drive and calibrate the batch-7 recovery fixtures through the real guarded v1 tools."""
from stat import S_IMODE

import pytest

from dev import dev_recovery as suite, fast12_runner
from lilguy import protocol


@pytest.mark.parametrize('task', suite.TASKS, ids=lambda t: t.id)
def test_recovery_controls(tmp_path, task):
    tools = protocol.load_tools()
    oracle_root, null_root = tmp_path / 'oracle', tmp_path / 'null'
    oracle = fast12_runner.run_oracle(oracle_root, task, tools, suite.grade)
    null = fast12_runner.run_false_done(null_root, task, tools, suite.grade)
    for record in (oracle, null):
        assert record['infra_error'] is None, record
        assert record['original_unchanged'] is True
    assert oracle['failures'] == [], oracle
    assert null['failures'], null
    for path in task.files:
        assert S_IMODE((oracle_root / 'work' / path).stat().st_mode) == S_IMODE(
            (null_root / 'work' / path).stat().st_mode)
