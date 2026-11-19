"""Live corpus v2 calibration: one example per family through guarded gold run and replay."""
import pytest

from dev import v2_corpus as v2


def _one_per_family():
    seen = {}
    for example in v2.generate(scale=0.05):
        seen.setdefault(example.family, example)
    return list(seen.values())


@pytest.mark.parametrize('task', _one_per_family(), ids=lambda task: task.id)
def test_v2_example_verifies_and_replays(task):
    status, payload = v2.verify_one(task)
    assert status == 'ok', payload
    assert payload['staged'] == task.changes
