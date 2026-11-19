"""Shared v1 loop/recorder core: one definition of how a trajectory is driven and recorded.

Interface v1 itself (action syntax, observation format, system prompt, grammar) lives in
`lilguy/protocol.py` and is not touched here. This module is the other half every drive needs
regardless of where actions come from (a scripted oracle, a stock model, a false-done probe):
turn-by-turn execution against an already-open tool session, honest termination, and a complete
record of what happened.

Fail-closed contract, frozen: once an observation's policy line reports `pending` or `rejected`,
the only action accepted next is `ask` or `done`; anything else is immediately terminal
`invalid` and is never executed. This is the same guarantee callers previously hand-rolled; it
now has exactly one implementation.

Honest termination kinds produced by `run_loop`:
  done      -- the trajectory finished and said so.
  ask       -- the trajectory handed back a question; not a failure.
  budget    -- `max_turns` turns ran out without a terminal action.
  exhausted -- `next_action` had nothing left to try (returned None).
  invalid   -- the fail-closed policy violation above, or `next_action` raised
               protocol.ProtocolError (a malformed action was produced and never executed).

Any other exception from `next_action` or `call_tool` propagates uncaught: that is a caller's
own infrastructure concern (e.g. an oracle script replay harness), not a trajectory outcome, and
this module must never swallow it into a misleadingly "successful" terminal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Sequence

from . import protocol as p

_POLICY_RE = re.compile(r"policy: (ok|pending|rejected)(?: \([^\r\n]*\))?")

TERMINAL_KINDS = ("done", "ask", "budget", "exhausted", "invalid")


def policy_of(text: str) -> str:
    """Only the final footer from render_observation carries policy authority."""
    match = _POLICY_RE.fullmatch(text.rpartition('\n')[2])
    return match.group(1) if match else "unknown"


@dataclass(frozen=True)
class Turn:
    """One executed non-terminal action and the observation it produced."""
    action: "p.Action"
    observation: str
    is_error: bool


@dataclass(frozen=True)
class Record:
    """The complete, honest record of one v1 trajectory: version, request, every turn, and how
    it ended. This is what any drive (scripted, model, or otherwise) must be able to produce;
    callers may project it into their own JSON contract, but nothing here is drive-specific."""
    version: int
    request: str
    terminal: str
    answer: Optional[str]
    turns: tuple

    def to_jsonable(self) -> dict:
        return {
            "version": self.version,
            "request": self.request,
            "terminal": self.terminal,
            "answer": self.answer,
            "turns": [
                {
                    "action": {
                        "kind": t.action.kind, "text": t.action.text,
                        "tool": t.action.tool, "args": t.action.args,
                    },
                    "observation": t.observation,
                    "is_error": t.is_error,
                }
                for t in self.turns
            ],
        }


# `call_tool(action) -> (observation_text, is_error)`, async; the caller owns the live session.
def replay_lines(saved: dict, tools) -> list[str]:
    """Decode a completed v1 recording into actions; grants no execution authority."""
    if saved.get('version') != p.INTERFACE_VERSION or saved.get('terminal') not in ('ask', 'done'):
        raise p.ProtocolError('expected a completed interface-v1 recording')
    actions = [p.Action(**turn['action']) for turn in saved['turns']]
    if any(action.kind not in ('tool', 'run') for action in actions):
        raise p.ProtocolError('unexpected terminal action inside recording')
    actions.append(p.Action(saved['terminal'], text=saved['answer']))
    lines = [p.render_action(action, tools) for action in actions]
    if any(p.parse_action(line, tools) != action for line, action in zip(lines, actions)):
        raise p.ProtocolError('recording contains a non-round-tripping action')
    return lines


CallTool = Callable[["p.Action"], Awaitable[tuple]]
# `next_action(turns, policy) -> Action | None`, sync; may raise protocol.ProtocolError.
NextAction = Callable[[Sequence[Turn], str], Optional["p.Action"]]


async def run_loop(call_tool: CallTool, request: str, next_action: NextAction, max_turns: int,
                    *, version: int = p.INTERFACE_VERSION) -> Record:
    """Drive one honest v1 trajectory to a terminal state and return its full Record.

    See module docstring for the fail-closed contract and the terminal kinds produced.
    """
    turns: list = []
    policy = "ok"
    for _ in range(max_turns):
        try:
            action = next_action(turns, policy)
        except p.ProtocolError:
            return Record(version, request, "invalid", None, tuple(turns))
        if action is None:
            return Record(version, request, "exhausted", None, tuple(turns))
        if policy != "ok" and action.kind not in ("ask", "done"):
            return Record(version, request, "invalid", None, tuple(turns))
        if action.kind in ("ask", "done"):
            return Record(version, request, action.kind, action.text, tuple(turns))
        text, is_error = await call_tool(action)
        policy = policy_of(text)
        turns.append(Turn(action, text, is_error))
        if policy == 'unknown':
            return Record(version, request, 'invalid', None, tuple(turns))
    return Record(version, request, "budget", None, tuple(turns))
