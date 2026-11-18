import asyncio
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from lilguy import cli
from lilguy.sandbox import layers, persist

ROOT = Path(__file__).resolve().parents[2]


def parameters(workspace, state):
    # Only the trusted outer server needs the user systemd runtime for cgroups.
    env = {k: os.environ[k] for k in ("XDG_RUNTIME_DIR",) if k in os.environ}
    return StdioServerParameters(command=sys.executable, cwd=ROOT, env=env, args=[
        "-m", "lilguy.mcp_server", "--workspace", str(workspace),
        "--state-dir", str(state), "--toolset", str(ROOT / "toolset.yaml"),
    ])


def test_stdio_registration_and_validation(tmp_path):
    async def run():
        with anyio.fail_after(20):
            async with stdio_client(parameters(tmp_path / "unused", tmp_path / "state")) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    assert {tool.name for tool in (await client.list_tools()).tools} == {
                        "fs.find", "fs.read", "fs.edit",
                    }
                    result = await client.call_tool("fs.read", {"path": "../outside"})
                    assert result.isError
                    assert "workspace-relative" in result.content[0].text

    asyncio.run(run())
    assert not (tmp_path / "state").exists()


@pytest.mark.sandbox
def test_stdio_find_read_edit_external_review(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    target = workspace / "-settings.txt"
    original = b"header\r\nsetting=a.*\r\n"
    updated = b"header\r\nsetting=$HOME\r\n"
    target.write_bytes(original)
    outside = tmp_path / "outside"
    outside.write_text("fixture outside")
    (workspace / "escape").symlink_to(outside)

    async def run():
        with anyio.fail_after(45):
            async with stdio_client(parameters(workspace, state)) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    found = await client.call_tool("fs.find", {"name_glob": "-*.txt", "type": "f"})
                    assert not found.isError and "-settings.txt" in found.content[0].text
                    read_result = await client.call_tool("fs.read", {"path": "-settings.txt", "offset": 2})
                    assert not read_result.isError and "setting=a.*" in read_result.content[0].text
                    assert "header" not in read_result.content[0].text
                    assert (await client.call_tool("fs.read", {"path": "escape"})).isError
                    edited = await client.call_tool("fs.edit", {
                        "path": "-settings.txt", "old": "a.*", "new": "$HOME",
                    })
                    assert not edited.isError
                    staged = await client.call_tool("fs.read", {"path": "-settings.txt", "offset": 2})
                    assert not staged.isError and "setting=$HOME" in staged.content[0].text
                    assert (await client.call_tool("fs.edit", {
                        "path": "-settings.txt", "old": "absent", "new": "ignored",
                    })).isError
                    assert target.read_bytes() == original

    asyncio.run(run())
    directory, = [path for path in state.iterdir() if (path / "progress.json").is_file()]
    assert cli.main(["diff", str(directory)]) == 0
    assert "-settings.txt" in capsys.readouterr().out
    session = persist.load_session(directory)
    assert layers.resolve(session, "-settings.txt").read_bytes() == updated
    assert target.read_bytes() == original
    audit = (directory / "audit.jsonl").read_text()
    assert "a.*" not in audit and "$HOME" not in audit
