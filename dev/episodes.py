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
    if saved.get('version') != p.INTERFACE_VERSION:
        raise ValueError(f"episode is interface v{saved.get('version')!r}, not v{p.INTERFACE_VERSION}")
    if saved.get('terminal') not in TRAINABLE or not saved.get('answer'):
        raise ValueError(f"episode ended {saved.get('terminal')!r}; only finished done/ask episodes train")
    messages = [{'role': 'system', 'content': p.system_prompt(tools)},
                {'role': 'user', 'content': saved['request']}]
    for turn in saved['turns']:
        action = p.Action(**turn['action'])
        if action.kind not in ('run', 'tool'):
            raise ValueError('a terminal action appears before the end of the episode')
        messages.append({'role': 'assistant', 'content': p.render_action(action, tools)})
        messages.append({'role': 'user', 'content': p.observation_message(turn['observation'])})
    final = p.Action(saved['terminal'], text=saved['answer'])
    messages.append({'role': 'assistant', 'content': p.render_action(final, tools)})
    for message in messages:
        if message['role'] == 'assistant':
            p.parse_action(message['content'], tools)  # raises ProtocolError on any drift
    return messages
