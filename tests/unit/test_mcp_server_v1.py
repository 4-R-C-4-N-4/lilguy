"""Red-first unit tests for the interface v1 guarded MCP server (step 2).

The pilot tracer (Tracer/load_tools/serve) stays untouched and is exercised by
tests/unit/test_p3_tools.py and tests/sandbox/test_p3_tracer.py. These tests cover the new
opt-in `--interface-v1` server: protocol.load_tools()'s five typed tools plus `run`, dispatched
through the same GuardedSession, with policy outcome + changes rendered via
protocol.render_observation. No apply/approve tool is ever registered.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lilguy import protocol
from lilguy.mcp_server import InterfaceV1, build_v1_tools
from lilguy.policy.engine import Decision
from lilguy.sandbox.backend import DiffEntry, RunSpec, StepResult

TOOLS = protocol.load_tools()


def _guarded(exit_code=0, stdout="", stderr="", tags=(), step_diff=(), decision=Decision("ok")):
    guarded = Mock()
    guarded.run.return_value = SimpleNamespace(
        decision=decision,
        result=StepResult(exit_code, stdout, stderr, ".", list(tags), list(step_diff), 0),
    )
    return guarded


def test_served_tools_are_exactly_v1_typed_tools_plus_run():
    tools = build_v1_tools()
    assert set(tools) == {"run", "fs.list", "fs.find", "fs.read", "fs.grep", "fs.edit"}
    assert tools["run"].inputSchema["required"] == ["command"]
    assert tools["fs.read"].inputSchema["required"] == ["path"]
    assert tools["fs.find"].inputSchema["properties"]["max_depth"]["maximum"] == 20


def test_no_apply_or_approval_tool_is_ever_registered():
    tools = build_v1_tools()
    forbidden = {"apply", "approve", "approval", "commit", "deny"}
    assert not (set(tools) & forbidden)


def test_run_dispatches_a_shell_runspec_through_guarded_session():
    guarded = _guarded(stdout="hi\n")
    server = InterfaceV1(build_v1_tools(), lambda: guarded)
    result = server.call("run", {"command": "echo hi"})
    spec: RunSpec = guarded.run.call_args.args[0]
    assert spec.shell == "echo hi" and spec.argv is None and spec.pipe is None
    assert guarded.run.call_args.kwargs == {"typed_tool": None}
    assert not result.isError
    assert "exit=0" in result.content[0].text
    assert "policy: ok" in result.content[0].text
    assert "changes: none" in result.content[0].text


def test_typed_tool_dispatches_through_typed_step_program_like_the_tracer():
    guarded = _guarded(stdout="a.txt\n")
    server = InterfaceV1(build_v1_tools(), lambda: guarded)
    server.call("fs.find", {"path": "."})
    spec: RunSpec = guarded.run.call_args.args[0]
    assert spec.argv[:4] == ["/usr/bin/python3", "-I", "-c", spec.argv[3]]
    assert spec.argv[4:6] == ["fs.find", "--"]
    assert guarded.run.call_args.kwargs == {"typed_tool": "fs.find", "tool_args": [["path", "."]]}


@pytest.mark.parametrize(("name", "args"), [
    ("run", {}),
    ("run", {"command": ""}),
    ("apply", {}),
    ("fs.read", {"path": "/outside"}),
    ("fs.read", {"path": "a/../b"}),
    ("fs.find", {"max_depth": -1}),
    ("fs.edit", {"path": "a", "old": "", "new": "b"}),
])
def test_invalid_calls_never_open_a_session(name, args):
    open_guarded = Mock()
    result = InterfaceV1(build_v1_tools(), open_guarded).call(name, args)
    assert result.isError
    open_guarded.assert_not_called()


def test_pending_outcome_is_surfaced_as_policy_pending_observation():
    guarded = _guarded(decision=Decision("pending", "rule", "too many deletes"))
    server = InterfaceV1(build_v1_tools(), lambda: guarded)
    result = server.call("run", {"command": "rm a b c"})
    assert "policy: pending (too many deletes)" in result.content[0].text


def test_rejected_outcome_is_surfaced_as_policy_rejected_observation():
    guarded = _guarded(exit_code=1, decision=Decision("reject", "protected", "touches .git"))
    server = InterfaceV1(build_v1_tools(), lambda: guarded)
    result = server.call("run", {"command": "rm .git/config"})
    assert result.isError
    assert "policy: rejected (touches .git)" in result.content[0].text


def test_unknown_decision_returns_infrastructure_error_not_a_policy_grant():
    from lilguy.loop import policy_of
    guarded = _guarded(decision=Decision('unrecognized'), stdout='private step output')
    result = InterfaceV1(build_v1_tools(), lambda: guarded).call('run', {'command': 'pwd'})
    assert result.isError and policy_of(result.content[0].text) == 'unknown'
    assert 'private step output' not in result.content[0].text
    guarded.run.assert_called_once()


def test_changes_are_rendered_from_the_step_diff():
    diff = [DiffEntry("added", "out.txt", "file"), DiffEntry("deleted", "old.txt", "file")]
    guarded = _guarded(step_diff=diff)
    server = InterfaceV1(build_v1_tools(), lambda: guarded)
    result = server.call("run", {"command": "mv old.txt out.txt"})
    assert "changes: added out.txt; deleted old.txt" in result.content[0].text


def test_guarded_session_open_failure_never_crashes_the_server():
    def boom():
        raise RuntimeError("sandbox unavailable")

    server = InterfaceV1(build_v1_tools(), boom)
    result = server.call("run", {"command": "echo hi"})
    assert result.isError


def test_interface_v1_server_is_opt_in_via_cli_flag(tmp_path):
    from lilguy import mcp_server

    parser_args = mcp_server._parse_args([
        "--workspace", str(tmp_path), "--state-dir", str(tmp_path / "state"),
        "--toolset", str(Path(__file__).resolve().parents[2] / "toolset.yaml"),
        "--interface-v1",
    ])
    assert parser_args.interface_v1 is True
    default_args = mcp_server._parse_args([
        "--workspace", str(tmp_path), "--state-dir", str(tmp_path / "state"),
        "--toolset", str(Path(__file__).resolve().parents[2] / "toolset.yaml"),
    ])
    assert default_args.interface_v1 is False


def test_read_only_flag_opens_sessions_whose_policy_rejects_every_change(tmp_path, monkeypatch):
    from lilguy import mcp_server
    from lilguy.policy.engine import Policy

    args = mcp_server._parse_args([
        "--workspace", str(tmp_path), "--state-dir", str(tmp_path / "state"),
        "--toolset", str(Path(__file__).resolve().parents[2] / "toolset.yaml"),
        "--interface-v1", "--read-only",
    ])
    assert args.read_only is True
    assert mcp_server.trusted_policies(read_only=True) == [Policy(read_only=True)]
    assert mcp_server.trusted_policies(read_only=False) is None
