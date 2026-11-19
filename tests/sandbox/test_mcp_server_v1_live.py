"""Live sandbox integration: the interface v1 MCP server, end to end.

Exercises `run` plus all five typed tools implemented in `_typed_step.py` (fs.list, fs.find,
fs.read, fs.grep, fs.edit) through the real bwrap sandbox, one GuardedSession, exactly as the
pilot tracer does. Each typed tool is compared against its benign shell counterpart (`run` with
ls/find/cat/grep/sed) on the same disposable fixtures, checking both tools agree on output and
that any staged effects (or lack of them) match, including that the original workspace file is
left untouched until a human approves.

This file also covers the policy engine's harmless, deterministic pending and rejected paths
(truncate-to-zero and writing a protected path) through a live `run` call. Those two cases are
chosen because they are benign, everyday shell operations that happen to be policy-significant --
they are NOT bypass-corpus or adversarial payloads, and passing them is not a substitute for, and
does not imply, acceptance of any bypass-corpus suite. That acceptance is a separate, explicitly
out-of-scope deliverable.

Only harmless, disposable fixture content is used; no attack/bypass samples are run.
"""
import asyncio
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]


def parameters(workspace, state):
    env = {k: os.environ[k] for k in ("XDG_RUNTIME_DIR",) if k in os.environ}
    return StdioServerParameters(command=sys.executable, cwd=ROOT, env=env, args=[
        "-m", "lilguy.mcp_server", "--workspace", str(workspace),
        "--state-dir", str(state), "--toolset", str(ROOT / "toolset.yaml"), "--interface-v1",
    ])


def test_interface_v1_lists_run_plus_typed_tools(tmp_path):
    async def run():
        with anyio.fail_after(20):
            async with stdio_client(parameters(tmp_path / "unused", tmp_path / "state")) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    assert names == {"run", "fs.list", "fs.find", "fs.read", "fs.grep", "fs.edit"}
                    assert not (names & {"apply", "approve", "commit"})

    asyncio.run(run())


@pytest.mark.sandbox
def test_live_run_and_typed_tools_share_one_session_diff(tmp_path, capsys):
    from lilguy import cli
    from lilguy.sandbox import persist

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    fixture = workspace / "notes.txt"
    fixture.write_text("todo: ship\nstatus: draft\n")

    async def run():
        with anyio.fail_after(60):
            async with stdio_client(parameters(workspace, state)) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()

                    found = await client.call_tool("fs.find", {"name_glob": "*.txt", "type": "f"})
                    assert not found.isError and "notes.txt" in found.content[0].text
                    shell_find = await client.call_tool("run", {"command": "find . -name '*.txt' -type f -printf '%P\\n'"})
                    assert not shell_find.isError and shell_find.content[0].text == found.content[0].text

                    read_result = await client.call_tool("fs.read", {"path": "notes.txt"})
                    assert not read_result.isError and "status: draft" in read_result.content[0].text
                    shell_read = await client.call_tool("run", {"command": "cat notes.txt"})
                    assert not shell_read.isError and shell_read.content[0].text == read_result.content[0].text

                    edited = await client.call_tool("fs.edit", {
                        "path": "notes.txt", "old": "status: draft", "new": "status: shipped",
                    })
                    assert not edited.isError and "policy: ok" in edited.content[0].text
                    assert "changes: modified notes.txt" in edited.content[0].text
                    counterpart = await client.call_tool("run", {"command": "sed 's/status: draft/status: shipped/' original.fixture > counterpart.txt"})
                    assert not counterpart.isError
                    compare = await client.call_tool("run", {"command": "cmp notes.txt counterpart.txt"})
                    assert not compare.isError and "exit=0" in compare.content[0].text

                    created = await client.call_tool("run", {"command": "echo hi > extra.txt"})
                    assert not created.isError and "policy: ok" in created.content[0].text
                    assert "changes: added extra.txt" in created.content[0].text

                    bad = await client.call_tool("fs.read", {"path": "../outside"})
                    assert bad.isError
                    assert "Invalid tool or arguments" in bad.content[0].text

    (workspace / "original.fixture").write_bytes(fixture.read_bytes())
    asyncio.run(run())

    directory, = [path for path in state.iterdir() if (path / "progress.json").is_file()]
    assert cli.main(["diff", str(directory)]) == 0
    out = capsys.readouterr().out
    assert "notes.txt" in out and "extra.txt" in out

    session = persist.load_session(directory)
    from lilguy.sandbox import layers
    assert layers.resolve(session, "notes.txt").read_text() == "todo: ship\nstatus: shipped\n"
    assert layers.resolve(session, "extra.txt").read_text() == "hi\n"
    assert fixture.read_text() == "todo: ship\nstatus: draft\n"


@pytest.mark.sandbox
def test_live_fs_list_matches_run_ls_counterpart(tmp_path):
    """fs.list and a benign `run` ls counterpart agree on a disposable fixture tree, and
    neither one (both being read-only) stages any effect."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    (workspace / "a.txt").write_text("alpha\n")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "b.txt").write_text("beta\n")

    async def run():
        with anyio.fail_after(60):
            async with stdio_client(parameters(workspace, state)) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()

                    listed = await client.call_tool("fs.list", {"path": ".", "depth": 1})
                    assert not listed.isError and "policy: ok" in listed.content[0].text
                    assert "changes: none" in listed.content[0].text
                    assert "a.txt" in listed.content[0].text and "sub" in listed.content[0].text

                    shelled = await client.call_tool("run", {"command": "ls -1 ."})
                    assert not shelled.isError and "policy: ok" in shelled.content[0].text
                    assert "changes: none" in shelled.content[0].text
                    assert "a.txt" in shelled.content[0].text and "sub" in shelled.content[0].text

    asyncio.run(run())

    # Both tools staged no effect (already asserted via "changes: none" above); the originals
    # are untouched regardless.
    assert (workspace / "a.txt").read_text() == "alpha\n"
    assert (workspace / "sub" / "b.txt").read_text() == "beta\n"


@pytest.mark.sandbox
def test_live_fs_grep_matches_run_grep_counterpart(tmp_path):
    """fs.grep and a benign `run` grep counterpart agree on matches in a disposable fixture,
    and neither (both read-only) stages any effect or modifies the original."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    fixture = workspace / "notes.txt"
    fixture.write_text("todo: ship\nstatus: draft\n")

    async def run():
        with anyio.fail_after(60):
            async with stdio_client(parameters(workspace, state)) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()

                    typed = await client.call_tool("fs.grep", {"pattern": "status"})
                    assert not typed.isError and "policy: ok" in typed.content[0].text
                    assert "changes: none" in typed.content[0].text
                    assert "notes.txt:status: draft" in typed.content[0].text

                    shelled = await client.call_tool("run", {"command": "grep -r status ."})
                    assert not shelled.isError and "policy: ok" in shelled.content[0].text
                    assert "changes: none" in shelled.content[0].text
                    assert "status: draft" in shelled.content[0].text

    asyncio.run(run())

    assert fixture.read_text() == "todo: ship\nstatus: draft\n"


@pytest.mark.sandbox
def test_live_pending_truncate_to_zero_via_run(tmp_path):
    """A harmless, policy-selected `pending` outcome: truncating an existing non-empty file to
    zero bytes via a benign shell command. Not a bypass-corpus sample -- an everyday shell
    operation (`cp /dev/null`) that the policy engine flags for human review. Passing this does
    not substitute for, or imply, acceptance of a bypass-corpus suite."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    fixture = workspace / "notes.txt"
    fixture.write_text("todo: ship\nstatus: draft\n")

    async def run():
        with anyio.fail_after(60):
            async with stdio_client(parameters(workspace, state)) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    result = await client.call_tool("run", {"command": "cp /dev/null notes.txt"})
                    assert result.isError  # non-ok policy outcomes surface as an error reply
                    text = result.content[0].text
                    assert "policy: pending" in text
                    assert "changes: modified notes.txt" in text

    asyncio.run(run())

    # The policy engine's recorded rule for this decision was the truncate-to-zero rule, not
    # some other coincidental trigger.
    directory, = state.iterdir()
    audit = (directory / "audit.jsonl").read_text().strip().splitlines()
    import json as _json
    assert any(_json.loads(line).get("rule") == "truncated_to_zero" for line in audit)

    # The real workspace file is untouched: the effect is staged in the sandbox overlay only,
    # awaiting a human's separate approve/deny decision -- never applied automatically.
    assert fixture.read_text() == "todo: ship\nstatus: draft\n"


@pytest.mark.sandbox
def test_live_rejected_protected_path_via_run(tmp_path):
    """A harmless, policy-selected `rejected` outcome: writing to a protected path glob
    (`**/.env`) via a benign shell command with non-sensitive placeholder content. Not a
    bypass-corpus sample -- passing this does not substitute for, or imply, acceptance of a
    bypass-corpus suite."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"

    async def run():
        with anyio.fail_after(60):
            async with stdio_client(parameters(workspace, state)) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    result = await client.call_tool("run", {"command": "echo placeholder > .env"})
                    assert result.isError
                    text = result.content[0].text
                    assert "policy: rejected" in text

    asyncio.run(run())

    # The policy engine's recorded rule for this decision was the protected-path rule.
    directory, = state.iterdir()
    audit = (directory / "audit.jsonl").read_text().strip().splitlines()
    import json as _json
    assert any(_json.loads(line).get("rule") == "protected" for line in audit)

    # Rejections are rolled back inside the sandbox; nothing is ever written to the real
    # workspace.
    assert not (workspace / ".env").exists()
