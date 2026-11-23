"""Corpus revision 11: r10 re-recorded on interface v5 plus the five round-11 families."""
from collections import Counter

import pytest

from dev import v2_corpus as v2


@pytest.fixture(scope='module')
def corpora():
    return v2.generate(revision=10), v2.generate(revision=11)


def test_revision_11_is_r10_on_v5_plus_only_the_new_families(corpora):
    r10, r11 = corpora
    assert v2.interface_for(11) == 5 and {e.interface for e in r11} == {5}
    old = {e.id: e for e in r10}
    new = {e.id: e for e in r11}
    assert set(old) <= set(new)
    assert all(new[i].oracle == e.oracle and new[i].files == e.files for i, e in old.items())
    added = Counter(new[i].family for i in set(new) - set(old))
    assert added == {'append_after_marker': 72, 'named_file_missing': 60, 'named_file_present': 40,
                     'precise_count': 60, 'exact_create': 30}


def test_revision_10_is_unchanged_by_revision_11(corpora):
    r10, _ = corpora
    assert {e.interface for e in r10} == {4}
    assert not any(e.family in ('named_file_missing', 'precise_count') for e in r10)
    assert v2.generate(revision=10) == r10


def test_missing_file_episodes_ask_and_change_nothing(corpora):
    _, r11 = corpora
    missing = [e for e in r11 if e.family == 'named_file_missing']
    assert missing and all(e.terminal == 'ask' and not e.changes and e.oracle[-1].startswith('ask\n')
                           and e.oracle[-1].rstrip().endswith('?') for e in missing)
    # the named file is never in the fixture; the look-alikes are
    assert all(not any(path in e.request for path in e.files) for e in missing)


def test_counts_are_questions_whose_naive_count_differs(corpora):
    _, r11 = corpora
    counts = [e for e in r11 if e.family == 'precise_count']
    assert counts and all(e.mode == 'ask' and e.facts for e in counts)
    exact = [e for e in counts if 'grep -cx' in e.oracle[-2]]
    for e in exact:
        word = e.request.split('"')[1]
        body = next(iter(e.files.values()))
        assert sum(word in line for line in body.splitlines()) > int(e.facts[0])


def test_marker_appends_cover_both_endings_and_a_repair(corpora):
    _, r11 = corpora
    eol = [e for e in r11 if e.family == 'append_after_marker']
    endings = Counter(next(iter(e.files.values())).endswith('\n') for e in eol)
    assert endings[True] and endings[False] > endings[True]
    assert any(e.train_skip for e in eol)


def test_split_gate_covers_all_held_out_suites_for_revision_11():
    examples = v2.generate(revision=11)
    kept, _ = v2.dedup(examples)
    result = v2.gate(kept)
    assert result['ok'], result
