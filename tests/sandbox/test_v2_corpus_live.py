"""Live corpus v2 calibration: one example per family through guarded gold run and replay."""
import pytest

from dev import v2_corpus as v2


def _one_per_family():
    seen = {}
    for revision in (1, 2):
        for example in v2.generate(scale=0.05, revision=revision):
            seen.setdefault((example.family, example.request), (revision, example))
    first = {}
    for (family, _), item in seen.items():
        first.setdefault((item[0], family), item)
    return list(first.values())


@pytest.mark.parametrize('revision,task', _one_per_family(), ids=lambda x: x.id if hasattr(x, 'id') else f'rev{x}')
def test_v2_example_verifies_and_replays(revision, task):  # noqa: ARG001
    status, payload = v2.verify_one(task)
    assert status == 'ok', payload
    assert payload['staged'] == task.changes
