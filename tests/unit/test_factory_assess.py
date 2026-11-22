import pytest
from dev import factory_assess as a


def test_probe_has_only_prior_observations():
    row = {'mode': 'do', 'interface': 3, 'model': {'events': [
        {'action': {'kind': 'run', 'text': 'pwd'}, 'observation': 'previous'},
        {'action': {'kind': 'run', 'text': 'ls'}, 'observation': 'future'}]}}
    messages = a.prefix('inspect directory', row, 1)
    assert [m['role'] for m in messages] == ['system', 'user', 'assistant', 'user']
    assert 'previous' in messages[-1]['content'] and 'future' not in str(messages)
    with pytest.raises(ValueError):
        a.prefix('inspect directory', row, -1)


def test_trace_disagreement_refused():
    row = {'task': 't', 'infra_failure': False, 'passed': False, 'model': {'original_unchanged': True}}
    with pytest.raises(ValueError):
        a.check_trace(row, 't', True)
