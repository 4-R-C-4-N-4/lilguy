"""Corpus revision 12: revision 11 plus three contrast families, still on interface v5."""
from collections import Counter

from dev import v2_corpus as v2


def test_revision_12_is_r11_plus_only_the_contrasts():
    r11, r12 = v2.generate(revision=11), v2.generate(revision=12)
    assert v2.interface_for(12) == 5 and {e.interface for e in r12} == {5}
    old, new = {e.id: e for e in r11}, {e.id: e for e in r12}
    assert all(new[i] == e for i, e in old.items())
    added = Counter(new[i].family for i in set(new) - set(old))
    assert added == {'insert_under_heading': 84, 'recover_after_empty': 72, 'copy_folder_contents': 40}


def test_contrasts_never_append_and_recoveries_skip_the_slip():
    r12 = [e for e in v2.generate(revision=12) if e.id.startswith('v2-r12-')]
    inserts = [e for e in r12 if e.family == 'insert_under_heading']
    assert all(not step.startswith('run') for e in inserts for step in e.oracle)
    for e in inserts:  # the inserted line is never the file's last line
        (path, after), = e.changes.items()
        assert after.endswith(e.files[path].splitlines(keepends=True)[-1])
    recover = [e for e in r12 if e.family == 'recover_after_empty']
    assert all(e.mode == 'ask' and e.error_turns == (0,) and e.train_skip == (0,) and len(e.oracle) >= 3
               for e in recover)
    copies = [e for e in r12 if e.family == 'copy_folder_contents']
    assert all('/. ' in e.oracle[1] and e.oracle[2].startswith('tool fs.list') for e in copies)
