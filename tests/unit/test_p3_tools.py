from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lilguy.mcp_server import Tracer, load_tools
from lilguy.sandbox.backend import StepResult

TOOLSET = Path(__file__).resolve().parents[2] / "toolset.yaml"


def test_fixed_schema_and_guarded_dispatch():
    definitions = load_tools(TOOLSET)
    assert set(definitions) == {"fs.find", "fs.read", "fs.edit"}
    assert definitions["fs.read"].inputSchema["required"] == ["path"]
    assert definitions["fs.find"].inputSchema["properties"]["max_depth"]["maximum"] == 20
    guarded = Mock()
    guarded.run.return_value = SimpleNamespace(
        decision=SimpleNamespace(kind="ok"), result=StepResult(0, "fixture\n", "", ".", [], [], 0)
    )
    tracer = Tracer(definitions, lambda: guarded)
    result = tracer.call("fs.edit", {"path": "-fixture", "old": "a.*", "new": "$HOME"})
    spec = guarded.run.call_args.args[0]
    assert spec.argv[:4] == ["/usr/bin/python3", "-I", "-c", spec.argv[3]]
    assert spec.argv[4:6] == ["fs.edit", "--"]
    assert spec.shell is None and spec.pipe is None and not spec.network
    assert guarded.run.call_args.kwargs == {"typed_tool": "fs.edit"}
    assert not result.isError
    assert "fixture" in result.content[0].text


@pytest.mark.parametrize(("name", "args"), [
    ("exec", {}),
    ("fs.read", {"path": "/outside"}),
    ("fs.read", {"path": "a/../b"}),
    ("fs.read", {"path": "a", "offset": True}),
    ("fs.read", {"path": "a", "limit": 2001}),
    ("fs.read", {"path": "a", "network": True}),
    ("fs.find", {"max_depth": -1}),
    ("fs.edit", {"path": "a", "old": "", "new": "b"}),
])
def test_invalid_calls_never_open_a_session(name, args):
    open_guarded = Mock()
    result = Tracer(load_tools(TOOLSET), open_guarded).call(name, args)
    assert result.isError
    open_guarded.assert_not_called()


def test_read_digests_repeated_fixture_text_with_count_like_suffix():
    guarded = Mock()
    guarded.run.return_value = SimpleNamespace(
        decision=SimpleNamespace(kind="ok"),
        result=StepResult(0, "fixture  (xvalue)\nfixture\n", "", ".", [], [], 0),
    )
    result = Tracer(load_tools(TOOLSET), lambda: guarded).call("fs.read", {"path": "fixture"})
    assert not result.isError
    assert "fixture  (xvalue)" in result.content[0].text
