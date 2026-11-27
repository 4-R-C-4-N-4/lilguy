"""Revision 16 = revision 15 plus prefix-scoped spaces renames and glob recovery, nothing else."""
from collections import Counter

from dev import v2_corpus as v2


def test_revision_15_is_unchanged_by_revision_16():
    r15, r16 = {e.id: e for e in v2.generate(revision=15)}, {e.id: e for e in v2.generate(revision=16)}
    assert set(r15) <= set(r16)
    assert all((r15[i].oracle, r15[i].files, r15[i].changes) == (r16[i].oracle, r16[i].files, r16[i].changes)
               for i in r15)
    assert v2.interface_for(16) == 8 and all(e.interface == 8 for e in r16.values())
    assert Counter(r16[i].family for i in set(r16) - set(r15)) == {
        'rename_spaces_prefix': 40, 'rename_glob_recover': 30}


def test_revision_16_globs_use_current_names_and_mask_the_wrong_one():
    for e in v2.generate(revision=16, families={'rename_spaces_prefix', 'rename_glob_recover'}):
        calls = [step for step in e.oracle if step.startswith('tool fs.rename')]
        assert e.oracle[-1] == 'done'
        lead = calls[-1].split('glob: ')[1].split(' ')[0]
        assert calls[-1].endswith(f"glob: {lead} *{calls[-1].rsplit('*', 1)[1]}")  # current form: space kept
        if e.family == 'rename_glob_recover':
            assert len(calls) == 2 and '-*' in calls[0] and e.train_skip == (1,)
        else:
            assert len(calls) == 1 and e.train_skip == ()
