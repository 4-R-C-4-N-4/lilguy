"""Scoring tests for the additional development-only shell fixtures."""
from types import SimpleNamespace

from dev import dev_shell
from lilguy import protocol as p


def test_guessed_read_answer_without_a_successful_observation_fails():
    task = next(t for t in dev_shell.TASKS if t.id == 'utf8_line_count')
    kwargs = dict(terminal='done', answer='The file has 3 lines.', changes={}, original_unchanged=True)
    assert dev_shell.grade(task, events=[], **kwargs)
    event = (p.Action.run('wc -l -- journal.txt'), 'exit=0\n3 journal.txt\npolicy: ok', False)
    assert not dev_shell.grade(task, events=[event], **kwargs)
    assert dev_shell.grade(task, events=[(event[0], event[1], True)], **kwargs)
    assert dev_shell.grade(task, events=[event], **{**kwargs, 'answer': 'The file has 13 lines.'})


def test_exact_output_does_not_excuse_an_extra_effect_or_changes_to_originals():
    task = next(t for t in dev_shell.TASKS if t.id == 'quoted_label_index')
    model = dict(terminal='done', answer='Wrote label-index.txt.', events=[], original_unchanged=True)
    changes = {'label-index.txt': 'acorn\nfern\n'}
    assert not dev_shell.grade(task, changes=changes, **model)
    assert dev_shell.grade(task, changes={**changes, 'extra.txt': ''}, **model)
    assert dev_shell.grade(task, changes=changes, **{**model, 'original_unchanged': False})


def test_oracles_use_the_frozen_parser_and_only_add_files():
    tools = p.load_tools()
    for task in dev_shell.TASKS:
        actions = [p.parse_action(line, tools, 2) for line in task.oracle]
        assert actions[-1].kind == 'done'
        assert all(action.kind in {'run', 'tool'} for action in actions[:-1])
        assert task.changes.keys().isdisjoint(task.files)
        assert all(isinstance(value, str) for value in task.changes.values())


def test_untrusted_intermediate_observation_is_not_enough_for_read_evidence():
    task = SimpleNamespace(changes={}, answer_pattern=r'\bready\b')
    event = (p.Action.call('fs.read', path='status.txt'), 'exit=0\npolicy: ok\ntrailing text', False)
    assert dev_shell.grade(task, terminal='done', answer='ready', changes={}, events=[event],
                           original_unchanged=True)
