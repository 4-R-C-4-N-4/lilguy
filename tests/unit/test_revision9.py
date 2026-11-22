from dev import v2_corpus as c


def test_r9_is_additive_and_preserves_r8():
    old = c.generate(revision=8, scale=0.1)
    new = c.generate(revision=9, scale=0.1)
    assert new[:len(old)] == old
    extra = new[len(old):]
    assert {e.family for e in extra} == {'literal_script_create', 'literal_script_repair', 'select_record'}
    for e in extra:
        assert e.interface == 3 and e.oracle[-1] == 'done'
        if e.family == 'select_record':
            assert e.mode == 'ask' and not e.changes and e.facts
        else:
            assert len(e.changes) == 1 and e.mode == 'do'
            target, body = next(iter(e.changes.items()))
            assert (target in e.files) == (e.family == 'literal_script_repair')
            assert body.startswith('#!/bin/sh\n') and 'sh -n' in e.oracle[-2]
