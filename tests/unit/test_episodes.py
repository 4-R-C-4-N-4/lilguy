"""Recorded v1 episodes -> the chat messages a model sees at inference (training parity)."""
import pytest

from dev import episodes
from lilguy import loop
from lilguy import protocol as p

TOOLS = p.load_tools()


def record(terminal='done', answer='Changed notes.txt to status: ready.'):
    turns = (
        loop.Turn(p.Action.call('fs.read', path='notes.txt'), 'exit=0\nstatus: draft\nchanges: none\npolicy: ok', False),
        loop.Turn(p.Action.call('fs.edit', path='notes.txt', old='status: draft', new='status: ready'),
                  'exit=0\nchanges: modified notes.txt\npolicy: ok', False),
    )
    return loop.Record(p.INTERFACE_VERSION, 'Mark notes.txt ready.', terminal, answer, turns).to_jsonable()


def test_messages_match_the_inference_conversation():
    messages = episodes.to_messages(record(), TOOLS)
    assert [m['role'] for m in messages] == ['system', 'user', 'assistant', 'user', 'assistant', 'user', 'assistant']
    assert messages[0]['content'] == p.system_prompt(TOOLS)
    assert messages[1]['content'] == 'Mark notes.txt ready.'
    assert messages[3]['content'] == p.observation_message('exit=0\nstatus: draft\nchanges: none\npolicy: ok')
    assert p.parse_action(messages[-1]['content'], TOOLS) == p.Action.done('Changed notes.txt to status: ready.')


def test_every_assistant_turn_round_trips_through_the_parser():
    saved = record()
    assistant = [m['content'] for m in episodes.to_messages(saved, TOOLS) if m['role'] == 'assistant']
    expected = [p.Action(**t['action']) for t in saved['turns']] + [p.Action.done(saved['answer'])]
    assert [p.parse_action(text, TOOLS) for text in assistant] == expected


def test_a_clarification_ends_with_the_question():
    messages = episodes.to_messages(record('ask', 'Which config file did you mean?'), TOOLS)
    assert p.parse_action(messages[-1]['content'], TOOLS) == p.Action.ask('Which config file did you mean?')


@pytest.mark.parametrize('terminal', ['budget', 'invalid', 'exhausted'])
def test_unfinished_or_invalid_episodes_are_not_training_data(terminal):
    with pytest.raises(ValueError):
        episodes.to_messages(record(terminal, None), TOOLS)


def test_other_interface_versions_are_refused():
    saved = record()
    saved['version'] = p.INTERFACE_VERSION + 1
    with pytest.raises(ValueError):
        episodes.to_messages(saved, TOOLS)


def test_v1_episodes_keep_the_v1_prompt_and_v2_allows_a_bare_done():
    v1 = record()
    v1['version'] = 1
    assert episodes.to_messages(v1, TOOLS)[0]['content'] == p.system_prompt(TOOLS, version=1)
    bare = record(answer='')
    messages = episodes.to_messages(bare, TOOLS)
    assert messages[0]['content'] == p.system_prompt(TOOLS, version=2)
    assert messages[-1]['content'] == 'done'
    v1['answer'] = ''
    with pytest.raises(ValueError):
        episodes.to_messages(v1, TOOLS)
