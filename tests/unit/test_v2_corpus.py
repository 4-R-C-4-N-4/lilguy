"""Corpus v2 generator contracts that need no sandbox (the live replay check is in tests/sandbox)."""
from collections import Counter, defaultdict

import pytest

from dev import dev_categories, fast12, fast12_runner
from dev import v2_corpus as v2
from dev.broad_runner import development_rows, task_graders
from lilguy import protocol as p


@pytest.fixture(scope='module', params=[1, 2, 3, 4, 5, 6, 7], ids=['rev1', 'rev2', 'rev3', 'rev4', 'rev5', 'rev6', 'rev7'])
def corpus(request):
    return request.param, v2.generate(revision=request.param)


def test_generation_is_deterministic(corpus):
    revision, corpus = corpus
    again = v2.generate(revision=revision)
    assert [(e.id, e.request, e.files, e.oracle, e.changes) for e in corpus] == \
           [(e.id, e.request, e.files, e.oracle, e.changes) for e in again]
    assert v2.generate(seed=1)[0].request != corpus[0].request or v2.generate(seed=1)[0].files != corpus[0].files


def test_ids_unique_and_every_roadmap_category_covered(corpus):
    _, corpus = corpus
    assert len({e.id for e in corpus}) == len(corpus) >= 1000
    assert set(Counter(e.category for e in corpus)) == set(v2.CATEGORIES)


def test_oracles_are_canonical_v1_within_the_turn_budget(corpus):
    _, corpus = corpus
    tools = p.load_tools()
    for e in corpus:
        assert 2 <= len(e.oracle) <= fast12_runner.MAX_TURNS, e.id
        for line in e.oracle:
            assert p.render_action(p.parse_action(line, tools, 2), tools, 2) == line, e.id
        kinds = [line.split('\n', 1)[0].split(' ')[0] for line in e.oracle]
        assert kinds[-1] == e.terminal and all(k in ('run', 'tool') for k in kinds[:-1]), e.id


def test_answers_state_their_facts_and_honest_endings(corpus):
    revision, corpus = corpus
    if v2.interface_for(revision) >= 2:
        pytest.skip('interface v1 answer and clarification semantics; v2 is tested separately')
    for e in corpus:
        answer = e.oracle[-1].split('\n', 1)[1].casefold()
        for fact in e.facts:
            assert fact.casefold() in answer, (e.id, fact)
        if e.policy_end == 'pending':
            assert v2.PENDING in answer and 'deleted' not in answer, e.id
        if e.policy_end == 'rejected':
            assert 'rejected' in answer, e.id
        if e.terminal == 'ask':
            assert answer.rstrip().endswith('?') and e.changes == {}, e.id
        assert all(i < len(e.oracle) - 1 for i in e.error_turns + e.train_skip), e.id


def test_clarification_families_are_contrast_pairs(corpus):
    revision, corpus = corpus
    if v2.interface_for(revision) >= 2:
        pytest.skip('interface v1 answer and clarification semantics; v2 is tested separately')
    outcomes = defaultdict(set)
    for e in corpus:
        if e.category == 'ask':
            outcomes[e.family].add(e.terminal)
    assert outcomes and all(seen == {'ask', 'done'} for seen in outcomes.values()), outcomes
    terminals = Counter(e.terminal for e in corpus if e.category == 'ask')
    assert 0.4 <= terminals['ask'] / (terminals['ask'] + terminals['done']) <= 0.6


def test_dedup_removes_dev_and_internal_duplicates(corpus):
    _, corpus = corpus
    dev_task = fast12.TASKS[0]
    clone = v2.Example(id='v2-clone', family='x', category='edit', behaviour='x', request=dev_task.request,
                       files={'other.txt': 'x\n'}, oracle=(), changes={})
    twin = v2.Example(**{**corpus[0].__dict__, 'id': 'v2-twin'})
    kept, dropped = v2.dedup([corpus[0], twin, clone])
    assert [e.id for e in kept] == [corpus[0].id] and dropped == ['v2-twin', 'v2-clone']


def test_deduplicated_corpus_passes_the_frozen_split_gate(corpus):
    _, corpus = corpus
    kept, _ = v2.dedup(corpus)
    result = v2.gate(kept)
    assert result['ok'], result
    assert result['candidate_count'] == len(kept) + len(development_rows())


def test_skipped_slips_are_never_training_targets():
    messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'},
                {'role': 'assistant', 'content': 'a0'}, {'role': 'user', 'content': 'o0'},
                {'role': 'assistant', 'content': 'a1'}, {'role': 'user', 'content': 'o1'},
                {'role': 'assistant', 'content': 'a2'}]
    rows = v2.next_action_rows(messages, skip=(0,))
    assert [row[-1]['content'] for row in rows] == ['a1', 'a2']
    assert rows[0][2]['content'] == 'a0'  # still visible as history


def _events(*steps):
    return [(p.Action.run('true'), obs, err) for obs, err in steps]


def test_grader_requires_grounded_facts_and_honest_pending(corpus):
    revision, corpus = corpus
    if v2.interface_for(revision) >= 2:
        pytest.skip('interface v1 answer and clarification semantics; v2 is tested separately')
    task = next(e for e in corpus if e.policy_end == 'pending')
    answer = task.oracle[-1].split('\n', 1)[1]
    pending = 'exit=0\n(no output)\nchanges: deleted x\npolicy: pending (x)'
    ok = 'exit=0\nstdout (1 lines):\n  ' + ' '.join(task.facts) + '\nchanges: none\npolicy: ok'
    steps = [(ok, False)] * (len(task.oracle) - 2) + [(pending, True)]
    good = v2.grade(task, terminal='done', answer=answer, changes=task.changes, events=_events(*steps),
                    original_unchanged=True)
    assert good == []
    bad = v2.grade(task, terminal='done', answer='Deleted it.', changes=task.changes, events=_events(*steps),
                   original_unchanged=True)
    assert any('approval' in reason for reason in bad)


def test_facts_must_come_from_stdout_not_the_line_count_header():
    assert v2.stdout_text('exit=0\nstdout (3 lines):\n  a\n  b\nchanges: none\npolicy: ok') == '  a\n  b'
    assert v2.stdout_text('exit=1\nstderr (1 lines):\n  boom\nchanges: none\npolicy: ok') == ''


def test_every_development_task_has_a_report_category():
    ids = [t.id for t in fast12.TASKS] + [t.id for t, _ in task_graders()]
    assert {dev_categories.category(i) for i in ids} <= set(dev_categories.CATEGORIES)
    assert len(dev_categories.CATEGORY) == len(ids) == len(set(ids))


def test_revision_two_keeps_every_revision_one_family_and_adds_targeted_ones():
    one = {e.family for e in v2.generate(revision=1)}
    two = {e.family for e in v2.generate(revision=2)}
    assert one < two
    assert {'ask_conflict', 'ask_collision', 'idempotent_edit', 'conditional_copy'} <= two - one
    assert not any('backup' in path for e in v2.generate(revision=2) if e.family == 'ask_value' for path in e.files)


def test_revision_three_compares_before_claiming_a_collision_differs():
    two = {e.id: e for e in v2.generate(revision=2) if e.family == 'ask_collision'}
    three = {e.id: e for e in v2.generate(revision=3) if e.family == 'ask_collision'}
    assert set(two) == set(three)
    asks = [e for e in three.values() if e.terminal == 'ask']
    assert asks
    for e in asks:
        src = next(path for path in e.files if path.endswith('-v2.txt'))
        assert any(line.startswith('run\ncmp ') and src in line for line in e.oracle[:-1]), e.id
        assert e.error_turns == (1,), e.id
    unchanged = {e.id for e in v2.generate(revision=3)} - set(three)
    two_all = {e.id: e for e in v2.generate(revision=2)}
    three_all = {e.id: e for e in v2.generate(revision=3)}
    assert all(two_all[i] == three_all[i] for i in unchanged)


def test_revision_four_only_adds_output_orientation_episodes():
    three = v2.generate(revision=3)
    four = v2.generate(revision=4)
    added = [e for e in four if e.family == 'orient_output']
    assert [e for e in four if e.family != 'orient_output'] == three
    assert len(added) >= 100
    terminals = Counter(e.terminal for e in added)
    assert 0.4 <= terminals['ask'] / len(added) <= 0.6
    tools = p.load_tools()
    for e in added:
        out = e.meta['output']
        assert out not in e.files, e.id  # the named output does not exist yet
        assert ('tool fs.list\npath: .') in e.oracle, e.id  # orient on the inputs
        if e.train_skip:
            assert e.train_skip == (0,) and out in e.oracle[0], e.id  # the masked slip probes the output
        if e.terminal == 'ask':
            assert e.changes == {} and len(e.facts) == 2 and all(f in e.files for f in e.facts), e.id
            assert 'does not exist' not in e.oracle[-1], e.id
        else:
            assert set(e.changes) == {out}, e.id
        for line in e.oracle:
            assert p.render_action(p.parse_action(line, tools, 2), tools, 2) == line


def test_revision_5_is_interface_v2_with_bare_done_and_only_blocked_asks():
    r4 = {ex.id: ex for ex in v2.generate(scale=0.1, revision=4)}
    r5 = v2.generate(scale=0.1, revision=5)
    assert r5 and all(ex.interface == 2 for ex in r5)
    assert v2.interface_for(5) == 2 and v2.interface_for(4) == 1
    asks = {ex.family for ex in r5 if ex.terminal == 'ask'}
    assert asks <= set(v2.BLOCKED_ASK_FAMILIES)
    dropped = [i for i, ex in r4.items() if ex.terminal == 'ask' and ex.family not in v2.BLOCKED_ASK_FAMILIES]
    assert dropped and not {ex.id for ex in r5} & set(dropped)
    for ex in r5:
        old = r4[ex.id]
        assert ex.oracle[:-1] == old.oracle[:-1] and ex.changes == old.changes
        reported = ex.terminal == 'done' and (ex.changes or ex.policy_end != 'ok')
        assert (ex.oracle[-1] == 'done') == bool(reported), ex.id
        if not reported:
            assert ex.oracle[-1] == old.oracle[-1] and ex.facts == old.facts


def test_revision_5_grading_ignores_the_missing_report_but_not_the_effects():
    ex = next(e for e in v2.generate(scale=0.1, revision=5) if e.oracle[-1] == 'done' and e.policy_end == 'pending')
    events = [(None, 'exit=0\nchanges: modified x\npolicy: pending (x)', True)]
    kwargs = dict(terminal='done', answer='', events=events, original_unchanged=True)
    assert not [r for r in v2.grade(ex, changes=ex.changes, **kwargs) if 'pending' in r or 'terminal' in r]
    assert any('changes' in r for r in v2.grade(ex, changes={}, **kwargs))


def test_revision_6_adds_paired_read_only_families_and_more_questions():
    five = {ex.id: ex for ex in v2.generate(scale=0.2, revision=5)}
    six = v2.generate(scale=0.2, revision=6)
    by_id = {ex.id: ex for ex in six}
    assert v2.interface_for(6) == 2 and all(ex.interface == 2 for ex in six)
    assert set(five) <= set(by_id)
    for i, ex in five.items():
        assert by_id[i] == ex
    new = [ex for ex in six if ex.family in v2.READ_ONLY_FAMILIES]
    assert {ex.family for ex in new} == set(v2.READ_ONLY_FAMILIES)
    for family in v2.READ_ONLY_FAMILIES:
        members = [ex for ex in new if ex.family == family]
        looks = [ex for ex in members if not ex.changes]
        writes = [ex for ex in members if ex.changes]
        assert looks and writes, family
        for ex in looks:
            assert ex.oracle[-1].startswith('done\n') and ex.terminal == 'done'
            assert not any(line.startswith('tool fs.edit') for line in ex.oracle)
        for ex in writes:
            assert ex.oracle[-1] == 'done'
    answered = sum(ex.oracle[-1].startswith('done\n') for ex in six)
    bare = sum(ex.oracle[-1] == 'done' for ex in six)
    assert answered >= 0.75 * bare
    for ex in six:
        if ex.terminal == 'done' and not ex.changes and ex.policy_end == 'ok':
            assert ex.oracle[-1].startswith('done\n'), ex.id  # every question or no-op is answered


def test_revision_7_is_interface_v3_with_question_mode_and_answering_commands():
    six = {ex.id: ex for ex in v2.generate(scale=0.2, revision=6)}
    seven = v2.generate(scale=0.2, revision=7)
    assert v2.interface_for(7) == 3 and all(ex.interface == 3 for ex in seven)
    assert {ex.id for ex in seven} == set(six)  # same episodes, re-expressed for v3
    tools = p.load_tools()
    for ex in seven:
        for line in ex.oracle:
            assert p.render_action(p.parse_action(line, tools, 3), tools, 3) == line, ex.id
        if ex.terminal == 'done':
            assert ex.oracle[-1] == 'done'
        answer_only = ex.terminal == 'done' and not ex.changes and ex.policy_end == 'ok'
        assert (ex.mode == 'ask') == (answer_only and ex.family not in v2.DO_NOOP_FAMILIES), ex.id
        if answer_only:
            last = p.parse_action(ex.oracle[-2], tools, 3)
            assert not (last.kind == 'run' and p.is_literal_output(last.text)), ex.id
        if ex.mode == 'ask':  # a question never writes: no edit tool and no redirect into a file
            assert not any(line.startswith('tool fs.edit') for line in ex.oracle), ex.id
    asks = [ex for ex in seven if ex.terminal == 'ask']
    assert asks and all(ex.family in v2.BLOCKED_ASK_FAMILIES for ex in asks)
    modes = {ex.mode for ex in seven}
    assert modes == {'ask', 'do'}
