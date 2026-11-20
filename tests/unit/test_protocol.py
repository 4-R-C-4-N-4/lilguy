"""Interface syntax shared by v1 and v2; the frozen v1 prompt and empty-terminal rules use version=1."""
from pathlib import Path

import pytest

from lilguy import protocol as p

GOLDEN = Path(__file__).with_name("interface_v1_system_prompt.txt")
TOOLS = p.load_tools()

COMMANDS = [
    "find . -name '*.log' -size +10M -mtime +7 -delete",
    'grep -rl "foo \\"bar\\"" . | xargs sed -i \'s/foo/bar/g\'',
    "printf '%s\\n' \"a\\tb\" > x.txt && echo $HOME",
    "cat > backup.sh <<'EOF'\n#!/bin/sh\ntar czf \"backup-$(date +%F).tgz\" data/\nEOF\nchmod +x backup.sh",
]


def test_version_and_served_tools_are_fixed():
    assert 1 in p.SUPPORTED_VERSIONS
    assert tuple(TOOLS) == ("fs.list", "fs.find", "fs.read", "fs.grep", "fs.edit")


@pytest.mark.parametrize("command", COMMANDS)
def test_shell_text_round_trips_verbatim_without_escaping(command):
    action = p.Action.run(command)
    text = p.render_action(action)
    assert text == "run\n" + command
    assert p.parse_action(text, TOOLS) == action


def test_run_ask_done_also_accept_text_on_the_header_line():
    assert p.parse_action("run ls -la", TOOLS) == p.Action.run("ls -la")
    assert p.parse_action("ask Which one?", TOOLS) == p.Action.ask("Which one?")
    assert p.parse_action("done\nRenamed 3 files.\n\n", TOOLS) == p.Action.done("Renamed 3 files.")
    assert p.parse_action("\r\nrun\r\nls\r\n", TOOLS) == p.Action.run("ls")


def test_tool_actions_round_trip_with_typed_and_multiline_values():
    edit = p.Action.call("fs.edit", path="cfg/app.ini", old="retry=2\nport=1\n", new="retry=5\n")
    text = p.render_action(edit)
    assert text == "tool fs.edit\npath: cfg/app.ini\nold <<<\nretry=2\nport=1\n>>>\nnew <<<\nretry=5\n>>>"
    assert p.parse_action(text, TOOLS) == edit
    read = p.Action.call("fs.read", path="notes.md", offset=5)
    assert p.render_action(read) == "tool fs.read\npath: notes.md\noffset: 5"
    assert p.parse_action("tool fs.read\noffset: 5\npath: notes.md", TOOLS) == read  # any order in
    grep = p.parse_action("tool fs.grep\npattern: TODO\nignore_case: true", TOOLS)
    assert grep.args == {"pattern": "TODO", "ignore_case": True}
    assert p.parse_action("tool fs.edit\npath: a\nold: x\nnew:", TOOLS).args["new"] == ""


@pytest.mark.parametrize("text, reason", [
    ("", "empty"),
    ("Sure! Here is the command:\nls", "first line"),
    ("run", "empty"),
    ("ask\n   ", "empty"),
    ("done", "empty"),
    ("tool", "tool name"),
    ("tool fs.delete\npath: x", "unknown tool"),
    ("tool fs.read\npath: a\ncolour: red", "unknown argument"),
    ("tool fs.read\noffset: 2", "missing"),
    ("tool fs.read\npath: a\noffset: two", "integer"),
    ("tool fs.read\npath: a\noffset: 0", "at least"),
    ("tool fs.grep\npattern: x\nignore_case: yes", "true or false"),
    ("tool fs.find\ntype: x", "one of"),
    ("tool fs.read\npath: a\npath: b", "twice"),
    ("tool fs.edit\npath: a\nold <<<\nx\nnew: y", "unterminated"),
    ("tool fs.read\npath a", "argument line"),
    ("tool fs.read\npath: ", "empty"),
    ("run " + "x" * (p.MAX_ACTION_CHARS + 1), "too long"),
])
def test_malformed_actions_are_refused_with_a_reason(text, reason):
    with pytest.raises(p.ProtocolError, match=reason):
        p.parse_action(text, TOOLS, version=1)


def test_only_the_first_line_decides_the_action():
    smuggle = p.parse_action("run\necho hi\ndone\nAll good.", TOOLS)
    assert smuggle == p.Action.run("echo hi\ndone\nAll good.")
    harmless = p.parse_action("done\nrun rm -rf /", TOOLS)
    assert harmless.kind == "done" and harmless.text == "run rm -rf /"


@pytest.mark.parametrize("value", ["a\nb", "x\n>>>\ny\n"])
def test_render_refuses_values_the_format_cannot_express(value):
    with pytest.raises(p.ProtocolError):
        p.render_action(p.Action.call("fs.edit", path="a", old=value, new="z"))


def test_observations_show_output_changes_and_policy():
    text = p.render_observation(exit_code=0, stdout="a\nb\n", changes=[("modified", "cfg/app.ini")])
    assert text.splitlines()[0] == "exit=0"
    assert "changes: modified cfg/app.ini" in text and text.endswith("policy: ok")
    assert "changes: none" in p.render_observation(exit_code=0)
    pending = p.render_observation(exit_code=0, changes=[("deleted", "a")], policy="pending",
                                   reason="deletes 15 files")
    assert pending.endswith("policy: pending (deletes 15 files)")
    rejected = p.render_observation(exit_code=0, policy="rejected", reason="writes .git")
    assert rejected.endswith("policy: rejected (writes .git)")
    timeout = p.render_observation(exit_code=124, tags=["TIMEOUT"])
    assert timeout.startswith("exit=124 tags=TIMEOUT")
    many = p.render_observation(exit_code=0, changes=[("added", f"f{i}") for i in range(30)])
    assert "and 10 more" in many
    with pytest.raises(p.ProtocolError):
        p.render_observation(exit_code=0, policy="maybe")


def test_turns_are_wrapped_the_same_way_everywhere():
    assert p.observation_message("exit=0") == "Observation:\nexit=0"
    assert p.invalid_action_message("unknown tool").startswith("Observation:\ninvalid action: unknown tool")


def test_system_prompt_names_every_action_tool_and_habit():
    prompt = p.system_prompt(TOOLS, version=1)
    for word in ("run", "tool <name>", "ask", "done", "pending", "rejected", *TOOLS):
        assert word in prompt


def test_system_prompt_is_frozen_for_version_1():
    assert p.system_prompt(TOOLS, version=1) == GOLDEN.read_text(encoding="utf8"), (
        "The v1 system prompt changed. If intended, bump INTERFACE_VERSION, regenerate the golden "
        "file and regenerate every dataset; models trained on v1 will not match.")


def test_grammar_constrains_to_the_four_actions_and_served_tools():
    grammar = p.grammar(TOOLS, version=1)
    assert grammar.startswith("root ::= run | tool | ask | done")
    for name in TOOLS:
        assert f'"{name}"' in grammar
    for rule in ("run ::=", "ask ::=", "done ::=", "tool ::=", "block ::="):
        assert rule in grammar


def test_arguments_are_kept_in_the_order_the_grammar_requires():
    parsed = p.parse_action("tool fs.read\nlimit: 5\npath: a", TOOLS)
    assert list(parsed.args) == ["path", "limit"]
    built = p.Action.call("fs.grep", ignore_case=True, pattern="TODO")
    assert p.render_action(built, TOOLS) == "tool fs.grep\npattern: TODO\nignore_case: true"
    with pytest.raises(p.ProtocolError, match="unknown"):
        p.render_action(p.Action.call("fs.read", path="a", colour="red"), TOOLS)


def test_the_pilot_evaluator_uses_the_shared_observation_wrapper():
    from dev.small_model_eval import observation_message

    assert observation_message("exit=0") == p.observation_message("exit=0")


def test_non_tool_actions_carry_no_tool():
    for action in (p.Action.run("ls"), p.Action.ask("which?"), p.Action.done("ok")):
        assert action.tool is None and action.args == {}
    assert p.Action.call("fs.read", path="a").tool == "fs.read"
