"""Revision 14 = revision 13 on interface v6: archive episodes switch to the typed tools, plus two families."""
from collections import Counter

from dev import v2_corpus as v2
from lilguy import protocol


def test_revision_14_changes_only_archive_episodes_and_adds_two_families():
    r13, r14 = {e.id: e for e in v2.generate(revision=13)}, {e.id: e for e in v2.generate(revision=14)}
    assert v2.interface_for(14) == 6 and all(e.interface == 6 for e in r14.values())
    changed = Counter(r13[i].family for i in r13 if (r13[i].oracle, r13[i].files) != (r14[i].oracle, r14[i].files))
    assert set(changed) == {'tar_list', 'tar_extract', 'tar_extract_one'}
    assert all('tar -' not in step for e in r14.values() if e.family.startswith('tar_') for step in e.oracle)
    assert Counter(r14[i].family for i in set(r14) - set(r13)) == {
        'archive_tools': 60, 'permission_words': 48, 'archive_compare': 12}


def test_earlier_revisions_never_see_v6_tools():
    names = set(protocol.TOOLS_V6)
    for revision in (5, 8, 13):
        for e in v2.generate(revision=revision):
            assert not any(step.startswith('tool ') and step.split('\n')[0][5:] in names for step in e.oracle)
    assert tuple(v2._tools(5)) == protocol.TOOLS_V1 and set(protocol.TOOLS_V6) <= set(v2._tools(6))
