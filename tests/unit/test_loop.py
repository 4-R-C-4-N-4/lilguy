"""Red-first unit tests for lilguy/loop.py: the shared v1 loop/recorder core.

Pure in-memory tests: no sandbox, no model server. `call_tool` and `next_action` are both
fakes here; the live, guarded-sandbox exercise of edit/ask/approval-stop lives in
tests/sandbox/test_loop_live.py.
"""
import asyncio

import pytest

from lilguy import loop
from lilguy import protocol as p


def _sync_call_tool(script):
    """A call_tool fake: `script` is a list of (observation_text, is_error) to hand back in order."""
    it = iter(script)

    async def call_tool(action):
        return next(it)

    return call_tool


def test_policy_of_reads_the_policy_line():
    assert loop.policy_of("exit=0\nchanges: none\npolicy: ok") == "ok"
    assert loop.policy_of("exit=0\nchanges: none\npolicy: pending (truncated_to_zero)") == "pending"
    assert loop.policy_of("exit=0\nchanges: none\npolicy: rejected (protected)") == "rejected"
    assert loop.policy_of("no policy line here") == "unknown"


@pytest.mark.parametrize('observation', ['no policy line', 'policy: okay', 'policy: ok\ntrailing data'])
def test_unconfirmed_policy_stops_before_next_decision(observation):
    actions = iter([p.Action.run('pwd'), p.Action.done('finished')])
    record = asyncio.run(loop.run_loop(_sync_call_tool([(observation, True)]), 'r',
                                       lambda *_: next(actions), 2))
    assert record.terminal == 'invalid' and record.answer is None
    assert len(record.turns) == 1 and record.turns[0].observation == observation


def test_done_is_terminal_and_recorded_honestly():
    actions = iter([p.Action.run("ls"), p.Action.done("all good")])

    def next_action(turns, policy):
        return next(actions)

    call_tool = _sync_call_tool([("exit=0\nchanges: none\npolicy: ok", False)])
    record = asyncio.run(loop.run_loop(call_tool, "list files", next_action, max_turns=5))

    assert record.version == p.INTERFACE_VERSION
    assert record.request == "list files"
    assert record.terminal == "done"
    assert record.answer == "all good"
    assert len(record.turns) == 1
    assert record.turns[0].action == p.Action.run("ls")
    assert record.turns[0].observation == "exit=0\nchanges: none\npolicy: ok"
    assert record.turns[0].is_error is False


def test_ask_is_terminal_with_no_tool_call():
    def next_action(turns, policy):
        return p.Action.ask("which file?")

    record = asyncio.run(loop.run_loop(_sync_call_tool([]), "do a thing", next_action, max_turns=3))
    assert record.terminal == "ask"
    assert record.answer == "which file?"
    assert record.turns == ()


def test_exhausted_when_next_action_returns_none():
    def next_action(turns, policy):
        return None

    record = asyncio.run(loop.run_loop(_sync_call_tool([]), "r", next_action, max_turns=3))
    assert record.terminal == "exhausted"
    assert record.answer is None


def test_budget_when_turns_run_out_without_a_terminal_action():
    def next_action(turns, policy):
        return p.Action.run("echo hi")

    call_tool = _sync_call_tool([("exit=0\nchanges: none\npolicy: ok", False)] * 3)
    record = asyncio.run(loop.run_loop(call_tool, "r", next_action, max_turns=3))
    assert record.terminal == "budget"
    assert record.answer is None
    assert len(record.turns) == 3


def test_fails_closed_after_pending_policy():
    """Once policy is pending/rejected, only ask/done are accepted; anything else is `invalid`,
    with the attempted action never actually executed."""
    actions = iter([p.Action.run("truncate"), p.Action.run("try again anyway")])
    call_count = {"n": 0}

    def next_action(turns, policy):
        return next(actions)

    async def call_tool(action):
        call_count["n"] += 1
        return "exit=0\nchanges: modified f\npolicy: pending (truncated_to_zero)", True

    record = asyncio.run(loop.run_loop(call_tool, "r", next_action, max_turns=5))
    assert record.terminal == "invalid"
    assert record.answer is None
    # only the first (pending-triggering) action was actually executed
    assert call_count["n"] == 1
    assert len(record.turns) == 1


def test_pending_then_honest_done_is_accepted():
    actions = iter([p.Action.run("truncate"), p.Action.done("notes.txt is pending approval")])

    def next_action(turns, policy):
        return next(actions)

    async def call_tool(action):
        return "exit=0\nchanges: modified notes.txt\npolicy: pending (truncated_to_zero)", True

    record = asyncio.run(loop.run_loop(call_tool, "r", next_action, max_turns=5))
    assert record.terminal == "done"
    assert record.answer == "notes.txt is pending approval"
    assert len(record.turns) == 1


def test_rejected_then_ask_is_accepted():
    actions = iter([p.Action.run("write .env"), p.Action.ask("that path is protected, how should I proceed?")])

    def next_action(turns, policy):
        return next(actions)

    async def call_tool(action):
        return "exit=0\nchanges: none\npolicy: rejected (protected)", True

    record = asyncio.run(loop.run_loop(call_tool, "r", next_action, max_turns=5))
    assert record.terminal == "ask"
    assert record.answer == "that path is protected, how should I proceed?"


def test_protocol_error_from_next_action_is_terminal_invalid():
    def next_action(turns, policy):
        raise p.ProtocolError("not a well-formed action")

    record = asyncio.run(loop.run_loop(_sync_call_tool([]), "r", next_action, max_turns=3))
    assert record.terminal == "invalid"
    assert record.answer is None
    assert record.turns == ()


def test_non_protocol_errors_propagate_uncaught():
    class InfraError(RuntimeError):
        pass

    def next_action(turns, policy):
        raise InfraError("harness-specific failure")

    with pytest.raises(InfraError):
        asyncio.run(loop.run_loop(_sync_call_tool([]), "r", next_action, max_turns=3))


def test_tool_action_calls_call_tool_with_the_action_object():
    seen = []

    async def call_tool(action):
        seen.append(action)
        return "exit=0\nchanges: none\npolicy: ok", False

    actions = iter([p.Action.call("fs.read", path="a.txt"), p.Action.done("read it")])

    def next_action(turns, policy):
        return next(actions)

    record = asyncio.run(loop.run_loop(call_tool, "r", next_action, max_turns=5))
    assert record.terminal == "done"
    assert seen == [p.Action.call("fs.read", path="a.txt")]


def test_record_to_jsonable_round_trips_structure():
    def next_action(turns, policy):
        return p.Action.done("ok")

    record = asyncio.run(loop.run_loop(_sync_call_tool([]), "req", next_action, max_turns=1))
    data = record.to_jsonable()
    assert data == {
        "version": p.INTERFACE_VERSION, "request": "req", "terminal": "done",
        "answer": "ok", "turns": [], "mode": "do",
    }
    v2 = asyncio.run(loop.run_loop(_sync_call_tool([]), "req", next_action, max_turns=1, version=2))
    assert "mode" not in v2.to_jsonable()  # earlier versions keep their exact record shape


def test_turns_seen_by_next_action_grow_each_call():
    seen_lengths = []
    actions = iter([p.Action.run("a"), p.Action.run("b"), p.Action.done("done")])

    def next_action(turns, policy):
        seen_lengths.append(len(turns))
        return next(actions)

    call_tool = _sync_call_tool([("exit=0\nchanges: none\npolicy: ok", False)] * 2)
    asyncio.run(loop.run_loop(call_tool, "r", next_action, max_turns=5))
    assert seen_lengths == [0, 1, 2]
