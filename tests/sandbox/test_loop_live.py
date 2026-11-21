"""Live sandbox exercise of lilguy/loop.py: the shared v1 loop/recorder core, for real.

Three scenarios, each against a fresh disposable fixture, through the real guarded
interface-v1 MCP server (the same server test_mcp_server_v1_live.py uses):

  edit            -- fs.edit succeeds, `done` terminal, staged effect matches, original untouched.
  ask             -- `ask` is terminal with no tool call, no staged effect.
  approval-stop   -- a harmless pending-policy outcome (truncate-to-zero) forces fail-closed:
                     the loop records the pending observation and accepts only an honest `done`
                     next, never silently continuing or auto-approving.

Each scenario's exact scripted trajectory is replayed a second time against a fresh fixture to
check the Record's terminal/answer/turn text match, the staged effect matches, and the second
run's original fixture is untouched too -- i.e. the loop is a deterministic function of its
inputs, not stateful in some way that would make a second run diverge.

Only harmless, disposable fixture content; no attack/bypass samples; read-only scoring via the
same session_diff machinery the rest of the sandbox integration tests use.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from lilguy import loop
from lilguy import protocol as p
from lilguy.sandbox import layers, persist
from lilguy.sandbox.diff import session_diff

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.sandbox


def _server_params(workspace: Path, state: Path) -> StdioServerParameters:
    env = {k: os.environ[k] for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") if k in os.environ}
    return StdioServerParameters(command=sys.executable, cwd=ROOT, env=env, args=[
        "-m", "lilguy.mcp_server", "--workspace", str(workspace), "--state-dir", str(state),
        "--toolset", str(ROOT / "toolset.yaml"), "--interface-v1",
    ])


def _scripted(tools, lines):
    it = iter(lines)

    def next_action(turns, policy):
        try:
            line = next(it)
        except StopIteration:
            return None
        return p.parse_action(line, tools)

    return next_action


async def _drive_once(workspace: Path, state: Path, request: str, lines, max_turns=6):
    tools = p.load_tools()
    with anyio.fail_after(60):
        async with stdio_client(_server_params(workspace, state)) as (r, w):
            async with ClientSession(r, w) as client:
                await client.initialize()

                async def call_tool(action):
                    result = await client.call_tool(
                        action.tool or "run", action.args if action.tool else {"command": action.text})
                    return result.content[0].text, result.isError

                return await loop.run_loop(call_tool, request, _scripted(tools, lines), max_turns)


def _staged_changes(state: Path) -> dict:
    """Read-only: the net staged content change for the one session under `state`, if any."""
    sessions = list(state.glob("*/progress.json"))
    if not sessions:
        return {}
    session = persist.load_session(sessions[0].parent)
    changes = {}
    for entry in session_diff(session):
        if entry.op == "deleted":
            changes[entry.path] = None
            continue
        target = layers.resolve(session, entry.path)
        changes[entry.path] = target.read_text() if target is not None else None
    return changes


def _run_scenario(tmp_path, name, fixture_files, request, lines):
    workspace = tmp_path / name / "workspace"
    workspace.mkdir(parents=True)
    state = tmp_path / name / "state"
    for rel, text in fixture_files.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    record = asyncio.run(_drive_once(workspace, state, request, lines))
    changes = _staged_changes(state)
    originals_unchanged = all(
        (workspace / rel).read_text() == text for rel, text in fixture_files.items())
    return record, changes, originals_unchanged


# --- edit ----------------------------------------------------------------------------------

def _edit_lines():
    return [
        "tool fs.edit\npath: notes.txt\nold: status: draft\nnew: status: ready",
        "done",
    ]


def test_edit_reaches_done_with_the_staged_effect_matching():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        record, changes, originals_unchanged = _run_scenario(
            Path(tmp), "edit", {"notes.txt": "status: draft\n"},
            "change status to ready", _edit_lines())
    assert record.version == p.INTERFACE_VERSION
    assert record.terminal == "done"
    assert record.answer == ""
    assert len(record.turns) == 1
    assert "policy: ok" in record.turns[0].observation
    assert not record.turns[0].is_error
    assert changes == {"notes.txt": "status: ready\n"}
    assert originals_unchanged


def test_edit_replays_to_a_matching_effect_and_terminal():
    import tempfile
    results = []
    for i in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            results.append(_run_scenario(
                Path(tmp), f"edit{i}", {"notes.txt": "status: draft\n"},
                "change status to ready", _edit_lines()))
    (r1, c1, u1), (r2, c2, u2) = results
    assert r1.terminal == r2.terminal == "done"
    assert r1.answer == r2.answer
    assert [t.observation for t in r1.turns] == [t.observation for t in r2.turns]
    assert c1 == c2 == {"notes.txt": "status: ready\n"}
    assert u1 and u2


# --- ask -------------------------------------------------------------------------------------

def _ask_lines():
    return ["ask\nthere are two config files; which one did you mean?"]


@pytest.mark.parametrize('scenario', ['edit', 'ask', 'approval'])
def test_replay_from_saved_record_only(tmp_path, scenario):
    script, files = {
        'edit': (_edit_lines, {'notes.txt': 'status: draft\n'}),
        'ask': (_ask_lines, {'a.yaml': 'x', 'b.yaml': 'y'}),
        'approval': (_pending_then_done_lines, {'notes.txt': 'not empty\n'}),
    }[scenario]
    original, effects, untouched = _run_scenario(tmp_path, 'first', files, scenario, script())
    path = tmp_path / 'record.json'
    path.write_text(json.dumps(original.to_jsonable()))
    saved = json.loads(path.read_text())
    lines = loop.replay_lines(saved, p.load_tools())
    repeat, staged, unchanged = _run_scenario(tmp_path, 'second', files, saved['request'], lines)
    assert repeat.to_jsonable() == saved
    assert staged == effects and untouched and unchanged


def test_ask_is_terminal_with_no_staged_effect():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        record, changes, originals_unchanged = _run_scenario(
            Path(tmp), "ask",
            {"config/a.yaml": "timeout: 10\n", "config/b.yaml": "timeout: 10\n"},
            "set the timeout to 30", _ask_lines())
    assert record.terminal == "ask"
    assert record.answer == "there are two config files; which one did you mean?"
    assert record.turns == ()
    assert changes == {}
    assert originals_unchanged


def test_ask_replays_to_a_matching_terminal():
    import tempfile
    outcomes = []
    for i in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            outcomes.append(_run_scenario(
                Path(tmp), f"ask{i}",
                {"config/a.yaml": "timeout: 10\n", "config/b.yaml": "timeout: 10\n"},
                "set the timeout to 30", _ask_lines()))
    (r1, c1, u1), (r2, c2, u2) = outcomes
    assert r1.terminal == r2.terminal == "ask"
    assert r1.answer == r2.answer
    assert c1 == c2 == {}
    assert u1 and u2


# --- approval-stop (pending) -------------------------------------------------------------------

def _pending_then_done_lines():
    return [
        "run\ncp /dev/null notes.txt",
        "done",
    ]


def test_pending_policy_forces_approval_stop_then_honest_done():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        record, changes, originals_unchanged = _run_scenario(
            Path(tmp), "approval-stop", {"notes.txt": "todo: ship\nstatus: draft\n"},
            "clear out notes.txt", _pending_then_done_lines())
    assert record.terminal == "done"
    assert record.answer == ""
    assert len(record.turns) == 1
    assert "policy: pending" in record.turns[0].observation
    assert record.turns[0].is_error  # non-ok policy outcomes surface as a tool error
    assert changes == {"notes.txt": ""}
    assert originals_unchanged


def test_approval_stop_fails_closed_if_the_script_ignores_pending():
    """The same pending-triggering run, but the script tries another `run` instead of
    ask/done: the fail-closed contract must turn this `invalid`, and the second action must
    never actually execute (only one turn is ever recorded)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        record, changes, originals_unchanged = _run_scenario(
            Path(tmp), "approval-stop-bad", {"notes.txt": "todo: ship\nstatus: draft\n"},
            "clear out notes.txt",
            ["run\ncp /dev/null notes.txt", "run\necho should-not-run > extra.txt"])
    assert record.terminal == "invalid"
    assert record.answer is None
    assert len(record.turns) == 1
    assert "extra.txt" not in changes
    assert originals_unchanged


def test_approval_stop_replays_to_a_matching_effect_and_terminal():
    import tempfile
    outcomes = []
    for i in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            outcomes.append(_run_scenario(
                Path(tmp), f"approval-stop-replay{i}", {"notes.txt": "todo: ship\nstatus: draft\n"},
                "clear out notes.txt", _pending_then_done_lines()))
    (r1, c1, u1), (r2, c2, u2) = outcomes
    assert r1.terminal == r2.terminal == "done"
    assert r1.answer == r2.answer
    assert [t.observation for t in r1.turns] == [t.observation for t in r2.turns]
    assert c1 == c2 == {"notes.txt": ""}
    assert u1 and u2
