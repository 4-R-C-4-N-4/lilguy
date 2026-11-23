"""Interface v3: the model picks the tool, lilguy owns the answer; v1 and v2 stay reproducible."""
from pathlib import Path

import pytest

from lilguy import loop
from lilguy import protocol as p

TOOLS = p.load_tools()
V2_GOLDEN = Path(__file__).with_name("interface_v2_system_prompt.txt")
V3_GOLDEN = Path(__file__).with_name("interface_v3_system_prompt.txt")


def test_current_version_is_3_and_earlier_versions_stay_supported():
    assert p.INTERFACE_VERSION == 3  # the shipped model's; v4 is in development
    assert p.SUPPORTED_VERSIONS == (1, 2, 3, 4)
    with pytest.raises(p.ProtocolError):
        p.system_prompt(TOOLS, version=5)


def test_v2_prompt_is_unchanged_and_v3_is_frozen():
    assert p.system_prompt(TOOLS, version=2) == V2_GOLDEN.read_text(encoding="utf8")
    assert p.system_prompt(TOOLS) == V3_GOLDEN.read_text(encoding="utf8"), (
        "The v3 system prompt changed. If intended, bump INTERFACE_VERSION and regenerate data.")


def test_v3_prompt_explains_modes_and_quoted_answers():
    v3 = p.system_prompt(TOOLS)
    assert "Question:" in v3 and "Request:" in v3
    assert "output of your last command" in v3
    assert "Write nothing after it" in v3
    for word in ("run", "tool <name>", "ask", "done", "pending", "rejected", *TOOLS):
        assert word in v3


def test_done_takes_no_text_in_v3():
    assert p.parse_action("done", TOOLS) == p.Action.done()
    assert p.render_action(p.Action.done()) == "done"
    with pytest.raises(p.ProtocolError):
        p.parse_action("done\nsparrow at 10:24", TOOLS)
    with pytest.raises(p.ProtocolError):
        p.render_action(p.Action.done("sparrow"), TOOLS)
    assert p.parse_action("done\nsparrow", TOOLS, version=2) == p.Action.done("sparrow")
    assert p.parse_action("ask\nWhich file?", TOOLS) == p.Action.ask("Which file?")


def test_v3_grammar_has_a_bare_done():
    assert 'done ::= "done"' in p.grammar(TOOLS).splitlines()
    assert 'done ::= "done" ("\\n" text)?' in p.grammar(TOOLS, version=2)


def test_user_message_names_the_mode_from_v3_only():
    assert p.user_message("Which is latest?", "ask") == "Question: Which is latest?"
    assert p.user_message("Fix it.", "do") == "Request: Fix it."
    assert p.user_message("Fix it.", "do", version=2) == "Fix it."
    with pytest.raises(p.ProtocolError):
        p.user_message("x", "maybe")


OBS = p.render_observation(exit_code=0, stdout="2026-08-17T10:24Z\tsparrow\n", policy="ok")


def test_observation_stdout_returns_the_digested_body():
    assert p.observation_stdout(OBS) == "2026-08-17T10:24Z\tsparrow"
    failed = p.render_observation(exit_code=1, stdout="0\n", stderr="", policy="ok")
    assert p.observation_stdout(failed) == "0"
    assert p.observation_stdout(p.render_observation(exit_code=0, policy="ok")) == ""
    both = p.render_observation(exit_code=2, stdout="a\nb\n", stderr="warn\n", policy="ok")
    assert p.observation_stdout(both) == "a\nb"


def test_quoted_answer_is_the_last_steps_stdout_when_policy_is_ok():
    run = p.Action.run("LC_ALL=C sort arrivals.tsv | tail -n 1")
    turns = [loop.Turn(p.Action.run("ls"), p.render_observation(exit_code=0, stdout="x\n"), False),
             loop.Turn(run, OBS, False)]
    quote = p.quoted_answer(turns)
    assert quote == p.Quote(command="LC_ALL=C sort arrivals.tsv | tail -n 1", exit_code=0,
                            text="2026-08-17T10:24Z\tsparrow")
    assert p.quoted_answer([]) is None
    rejected = p.render_observation(exit_code=0, stdout="y\n", changes=[("added", "y")], policy="rejected",
                                    reason="read_only")
    assert p.quoted_answer([loop.Turn(run, rejected, True)]) is None
    typed = loop.Turn(p.Action.call("fs.read", path="a.txt"), OBS, False)
    assert p.quoted_answer([typed]).command == "tool fs.read path: a.txt"


def test_v3_records_replay_with_a_bare_done():
    saved = {"version": 3, "terminal": "done", "answer": "",
             "turns": [{"action": {"kind": "run", "text": "wc -l < a.log", "tool": None, "args": {}}}]}
    assert loop.replay_lines(saved, TOOLS) == ["run\nwc -l < a.log", "done"]


def test_literal_echo_is_not_a_computed_answer():
    for command in ("echo sparrow", "printf 'q101\\nq709\\n'", "  echo 'yes, identical'"):
        assert p.is_literal_output(command), command
    for command in ("cmp -s a b && echo same || echo differ", "echo $(( 3 + 4 ))", "wc -l < a.log",
                    "grep -c x f; echo done", "sort a | tail -n 1", "echo \"$x\""):
        assert not p.is_literal_output(command), command
    turns = [loop.Turn(p.Action.run("echo sparrow"), OBS, False)]
    assert p.quoted_answer(turns).literal is True
