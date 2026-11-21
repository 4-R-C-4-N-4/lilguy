"""Live corpus v2 calibration: every family variant through guarded gold run and replay."""
import pytest

from dev import v2_corpus as v2


def _variant(example):
    """Families can change shape by revision or mode: first action, length, terminal and masked slip."""
    return (example.family, example.oracle[0].split('\n', 1)[0], len(example.oracle), example.terminal,
            example.train_skip)


def _one_per_variant():
    seen = {}
    for revision in (1, 2, 3, 4, 5, 6, 7):
        for example in v2.generate(scale=0.05 if revision < 4 else 0.1, revision=revision):
            seen.setdefault(_variant(example), (revision, example))
    return list(seen.values())


@pytest.mark.parametrize('revision,task', _one_per_variant(), ids=lambda x: x.id if hasattr(x, 'id') else f'rev{x}')
def test_v2_example_verifies_and_replays(revision, task):  # noqa: ARG001
    status, payload = v2.verify_one(task)
    assert status == 'ok', payload
    assert payload['staged'] == task.changes
