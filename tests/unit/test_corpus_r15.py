"""Revision 15 = revision 14 on interface v8: adds four fs.rename families, nothing else changes."""
from collections import Counter

from dev import v2_corpus as v2
from lilguy import protocol


def test_revision_14_is_unchanged_by_revision_15():
    r14, r15 = {e.id: e for e in v2.generate(revision=14)}, {e.id: e for e in v2.generate(revision=15)}
    shared = set(r14) & set(r15)
    assert shared == set(r14)  # every revision-14 episode survives unchanged
    assert all((r14[i].oracle, r14[i].files, r14[i].changes) == (r15[i].oracle, r15[i].files, r15[i].changes)
               for i in shared)
    assert v2.interface_for(15) == 8 and all(e.interface == 8 for e in r15.values())
    assert Counter(r15[i].family for i in set(r15) - set(r14)) == {
        'rename_spaces': 50, 'rename_zero_pad': 50, 'rename_collision': 20, 'rename_twin': 40}


def test_no_revision_below_15_contains_fs_rename():
    for revision in range(1, 15):
        for e in v2.generate(revision=revision):
            assert not any(step.startswith('tool fs.rename') for step in e.oracle)


def test_revision_15_rename_episodes_use_fs_rename_or_a_scripted_twin():
    r15 = v2.generate(revision=15)
    new = [e for e in r15 if e.family in ('rename_spaces', 'rename_zero_pad', 'rename_collision', 'rename_twin')]
    assert new
    for e in new:
        has_rename_tool = any(step.startswith('tool fs.rename') for step in e.oracle)
        if e.family == 'rename_twin':
            assert not has_rename_tool  # none of the twins is a job for fs.rename
        else:
            assert has_rename_tool
        if e.family in ('rename_spaces', 'rename_zero_pad') and e.policy_end == 'pending':
            assert e.oracle[-1] == 'done'  # bare done right after the pending preview


def test_v8_tools_are_not_served_below_interface_8():
    names = set(protocol.TOOLS_V8)
    for revision in (5, 8, 13, 14):
        for e in v2.generate(revision=revision):
            assert not any(step.startswith('tool ') and step.split('\n')[0][5:] in names for step in e.oracle)
    assert set(protocol.TOOLS_V8) <= set(v2._tools(8))
