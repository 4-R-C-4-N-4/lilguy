"""The cleanup freezes names and definitions, not an expanded tool surface."""
import json

import yaml

from lilguy import protocol
from lilguy.mcp_server import build_v1_tools


EXPECTED = ("run", "fs.list", "fs.find", "fs.read", "fs.grep", "fs.edit")


def test_frozen_manifest_matches_server_and_protocol():
    manifest = yaml.safe_load(protocol.TOOLSET.read_text())
    assert manifest["status"] == "frozen-served"
    assert tuple(manifest["served"]) == EXPECTED
    assert set(manifest["tools"]) == set(EXPECTED[1:])
    assert tuple(protocol.load_tools()) == EXPECTED[1:]
    served = build_v1_tools()
    assert tuple(served) == EXPECTED
    assert manifest["run_schema"] == served["run"].inputSchema
    assert not (set(manifest["proposals"]) & set(served))


def test_proposals_are_not_in_any_supported_grammar_or_prompt():
    manifest = yaml.safe_load(protocol.TOOLSET.read_text())
    tools = protocol.load_tools()
    for version in protocol.SUPPORTED_VERSIONS:
        grammar = protocol.grammar(tools, version=version)
        prompt = protocol.system_prompt(tools, version=version)
        for name in tools:
            assert name in prompt
            # GBNF literals are JSON quoted a second time for grammar syntax.
            assert json.dumps(name) in grammar or name in grammar
        for name in manifest["proposals"]:
            assert name not in prompt
            assert name not in grammar
