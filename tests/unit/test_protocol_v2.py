"""Interface v2: done is not a report, ask only when blocked; v1 stays reproducible."""
from pathlib import Path

import pytest

from lilguy import loop
from lilguy import protocol as p

TOOLS = p.load_tools()
V1_GOLDEN = Path(__file__).with_name("interface_v1_system_prompt.txt")
V2_GOLDEN = Path(__file__).with_name("interface_v2_system_prompt.txt")


def test_current_version_is_2_and_both_versions_are_supported():
    assert p.INTERFACE_VERSION == 2
    assert p.SUPPORTED_VERSIONS == (1, 2)
    with pytest.raises(p.ProtocolError):
        p.system_prompt(TOOLS, version=3)


def test_v1_prompt_is_unchanged_and_v2_is_frozen():
    assert p.system_prompt(TOOLS, version=1) == V1_GOLDEN.read_text(encoding="utf8")
    assert p.system_prompt(TOOLS) == V2_GOLDEN.read_text(encoding="utf8"), (
        "The v2 system prompt changed. If intended, bump INTERFACE_VERSION and regenerate data.")


def test_v2_prompt_drops_ambiguity_asking_and_change_summaries():
    v2 = p.system_prompt(TOOLS)
    assert "could mean more than one" not in v2
    assert "Do not describe your changes" in v2
    assert "cannot do the request" in v2
    for word in ("run", "tool <name>", "ask", "done", "pending", "rejected", *TOOLS):
        assert word in v2


def test_bare_done_is_valid_in_v2_only():
    assert p.parse_action("done", TOOLS) == p.Action("done", text="")
    assert p.render_action(p.Action.done()) == "done"
    assert p.parse_action("done\nretry=2", TOOLS) == p.Action.done("retry=2")
    with pytest.raises(p.ProtocolError):
        p.parse_action("done", TOOLS, version=1)
    with pytest.raises(p.ProtocolError):
        p.render_action(p.Action.done(), version=1)
    for empty in ("ask", "run"):
        with pytest.raises(p.ProtocolError):
            p.parse_action(empty, TOOLS)


def test_v2_grammar_makes_the_done_text_optional():
    assert 'done ::= "done" ("\\n" text)?' in p.grammar(TOOLS)
    assert 'done ::= "done\\n" text' in p.grammar(TOOLS, version=1)


def test_replay_and_records_accept_both_versions():
    for version, final in ((1, "changed it"), (2, "")):
        saved = {"version": version, "terminal": "done", "answer": final,
                 "turns": [{"action": {"kind": "run", "text": "ls", "tool": None, "args": {}}}]}
        lines = loop.replay_lines(saved, TOOLS)
        assert lines[-1] == ("done\nchanged it" if version == 1 else "done")
