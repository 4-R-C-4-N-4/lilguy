"""The executed plan a human reviews before approving or committing: every step lilguy ran,
rebuilt from the session's own trusted audit log, never from what the model said it did."""
import json

from lilguy.mcp_server import audit_args
from lilguy.policy import approval
from lilguy.policy.session import GuardedSession
from lilguy.sandbox import layers
from lilguy.sandbox.backend import RunSpec, SessionConfig
from tests.unit.test_decision_cli import run_cli
from tests.unit.test_human_approval import LayerWriter, pending, write  # noqa: F401  (fixture)


def _step(command, decision="ok", exit_code=0, paths=(), tool="exec"):
    return {"tool": tool, "args": command, "exit": exit_code, "decision": decision, "rule": None,
            "step_diff": [{"op": "modified", "path": p} for p in paths], "tags": []}


def test_steps_list_each_command_in_order_with_outcome_and_changes(pending):  # noqa: F811
    ws, session, *_ = pending
    text = approval.render_steps(session.directory)
    first, second = text.index("echo notes > notes.txt"), text.index("cd src && chmod 000 main.c")
    assert first < second
    assert "2 steps" in text and "pending" in text
    assert "added notes.txt" in text and "src/main.c" in text
    assert "proposed by the model" in text


def test_approved_and_denied_steps_are_marked(pending):  # noqa: F811
    ws, session, *_ = pending
    with approval.decision_session(session.directory) as other:
        approval.approve(other, approval.load_request(other)["diff_hash"])
    assert "approved" in approval.render_steps(session.directory)
    lines = [json.loads(line) for line in (session.directory / "audit.jsonl").read_text().splitlines()]
    lines.append({"decision": "denied", "action": "rollback_step", "rolled_back": ["src/main.c"]})
    text = approval.steps_text(lines)
    assert "denied, rolled back" in text


def test_rejected_multiline_and_hostile_commands_render_safely():
    records = [
        _step({"shell": "printf 'a\\n' > a.txt\nprintf 'b\\n' > b.txt"}, paths=["a.txt", "b.txt"]),
        _step({"shell": "rm -rf .git"}, decision="reject", exit_code=0, paths=[".git/config"]),
        _step({"shell": "echo \x1b[2Jhi"}),
        _step({"argv": ["/bin/ls", "-la", "my dir"]}),
        {"decision": "network_requested", "command": "curl x"},  # not a step
    ]
    text = approval.steps_text(records)
    assert "4 steps" in text
    assert "$ printf 'a\\n' > a.txt" in text and "> printf 'b\\n' > b.txt" in text
    assert "rejected, rolled back" in text
    assert "\x1b" not in text and "\\x1b[2Jhi" in text
    assert "/bin/ls -la 'my dir'" in text


def test_unreadable_audit_is_reported_not_hidden(tmp_path):
    (tmp_path / "audit.jsonl").write_text(json.dumps(_step({"shell": "true"})) + "\n{broken\n")
    text = approval.render_steps(tmp_path)
    assert "$ true" in text and "unreadable" in text
    assert "no step history" in approval.render_steps(tmp_path / "missing").lower()


def test_typed_tool_shows_paths_but_records_free_text_only_by_length(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    session = layers.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    backend = LayerWriter()
    backend.actions = [(write("notes.txt", "new"), ".")]
    arguments = {"path": "notes.txt", "old": "secret-old-text", "new": "replacement"}
    shown = audit_args("fs.edit", arguments)
    assert shown == [["path", "notes.txt"], ["old", "<15 chars>"], ["new", "<11 chars>"]]
    GuardedSession(backend, session).run(RunSpec(argv=["unused"]), typed_tool="fs.edit", tool_args=shown)
    audit = (session.directory / "audit.jsonl").read_text()
    assert "secret-old-text" not in audit
    text = approval.render_steps(session.directory)
    assert "fs.edit path=notes.txt old=<15 chars> new=<11 chars>" in text
    assert audit_args("fs.list", {"show_hidden": True, "path": "src", "depth": 2}) == [
        ["path", "src"], ["depth", 2], ["show_hidden", True]]


def test_diff_approve_and_commit_show_the_executed_steps(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    for command, typed in (("diff", ""), ("approve", "n\n")):
        code, out, err = run_cli(monkeypatch, capsys, [command, str(session.directory)], typed=typed)
        assert "$ cd src && chmod 000 main.c" in out, command
    digest = approval.load_request(session)["diff_hash"]
    run_cli(monkeypatch, capsys, ["approve", str(session.directory), "--diff-hash", digest], tty=False)
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory)], typed="n\n")
    assert out.index("$ echo notes > notes.txt") < out.index("Changes to write") < out.index("Diff hash")
