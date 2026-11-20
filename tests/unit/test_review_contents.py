"""Changed file contents at review time: a line diff of what would reach the workspace."""
from lilguy.policy import approval
from lilguy.sandbox import diff, layers
from lilguy.sandbox.backend import SessionConfig
from tests.unit.test_decision_cli import run_cli
from tests.unit.test_human_approval import pending  # noqa: F401  (fixture)


def _session(tmp_path, files, step):
    ws = tmp_path / "ws"
    ws.mkdir()
    for name, text in files.items():
        (ws / name).parent.mkdir(parents=True, exist_ok=True)
        (ws / name).write_bytes(text if isinstance(text, bytes) else text.encode())
    session = layers.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    step(layers.new_layer(session))
    return session, diff.session_diff(session)


def test_modified_added_and_deleted_files_show_their_lines(tmp_path, monkeypatch):
    placeholders = []

    def step(upper):
        (upper / "notes.txt").write_text("status: ready\nowner: ivy\n")
        (upper / "new.txt").write_text("hello\n")
        (upper / "old.txt").write_text("")  # stands in for an overlay whiteout (deletion)
        placeholders.append(upper / "old.txt")
    monkeypatch.setattr(diff, "is_whiteout", lambda p: p in placeholders)
    session, entries = _session(tmp_path, {"notes.txt": "status: draft\nowner: ivy\n", "old.txt": "bye\n"}, step)
    assert {e.path: e.op for e in entries}["old.txt"] == "deleted"
    text = approval.render_contents(session, entries)
    assert "--- a/notes.txt" in text and "+++ b/notes.txt" in text
    assert "-status: draft" in text and "+status: ready" in text and " owner: ivy" in text
    assert "+hello" in text and "-bye" in text


def test_binary_hostile_and_long_files_are_summarised_safely(tmp_path):
    def step(upper):
        (upper / "blob.bin").write_bytes(b"\x00\x01\x02")
        (upper / "evil.txt").write_text("\x1b[2Jboom\n")
        (upper / "long.txt").write_text("".join(f"line {i}\n" for i in range(500)))
    session, entries = _session(tmp_path, {}, step)
    text = approval.render_contents(session, entries, per_file=20)
    assert "blob.bin: binary" in text
    assert "\x1b" not in text and "\\x1b[2Jboom" in text
    assert "line 0" in text and "line 499" not in text and "more line" in text


def test_diff_and_commit_show_contents_before_the_hash(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    code, out, err = run_cli(monkeypatch, capsys, ["diff", str(session.directory)])
    assert "+++ b/notes.txt" in out and "+x" in out
    digest = approval.load_request(session)["diff_hash"]
    run_cli(monkeypatch, capsys, ["approve", str(session.directory), "--diff-hash", digest], tty=False)
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory)], tty=False)
    assert out.index("+++ b/notes.txt") < out.index("Diff hash")
    assert out.strip().splitlines()[-1].startswith("Diff hash")
