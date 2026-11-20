"""Recorded interface-v1 episodes as training conversations.

`to_messages` turns a saved `lilguy.loop.Record` (its `to_jsonable()` form) into the exact chat
the model sees at inference: the v1 system prompt, the request, then each action rendered in
canonical v1 form and each observation wrapped by `protocol.observation_message`, ending with
the terminal `done` or `ask`. Only finished episodes are training data; budget, invalid and
exhausted endings are refused rather than taught.
"""
from __future__ import annotations

from lilguy import protocol as p

TRAINABLE = ('done', 'ask')


def to_messages(saved: dict, tools) -> list[dict]:
    """The episode in the interface version it was recorded under (v1 data stays v1)."""
    version = saved.get('version')
    if version not in p.SUPPORTED_VERSIONS:
        raise ValueError(f"episode is interface v{version!r}, not one of {p.SUPPORTED_VERSIONS}")
    bare_done = version >= 2 and saved.get('terminal') == 'done' and saved.get('answer') == ''
    if saved.get('terminal') not in TRAINABLE or not (saved.get('answer') or bare_done):
        raise ValueError(f"episode ended {saved.get('terminal')!r}; only finished done/ask episodes train")
    messages = [{'role': 'system', 'content': p.system_prompt(tools, version)},
                {'role': 'user', 'content': saved['request']}]
    for turn in saved['turns']:
        action = p.Action(**turn['action'])
        if action.kind not in ('run', 'tool'):
            raise ValueError('a terminal action appears before the end of the episode')
        messages.append({'role': 'assistant', 'content': p.render_action(action, tools, version)})
        messages.append({'role': 'user', 'content': p.observation_message(turn['observation'])})
    final = p.Action(saved['terminal'], text=saved['answer'])
    messages.append({'role': 'assistant', 'content': p.render_action(final, tools, version)})
    for message in messages:
        if message['role'] == 'assistant':
            p.parse_action(message['content'], tools, version)  # raises ProtocolError on any drift
    return messages
