"""`lilguy commit` / `lilguy undo`: the only way sandbox changes reach the real workspace."""
import json
import os
from pathlib import Path, PurePosixPath

from lilguy.policy import approval
from lilguy.policy import commit as commitmod
from tests.unit.test_decision_cli import run_cli
from tests.unit.test_human_approval import pending  # noqa: F401  (fixture)


def _approve(session, monkeypatch, capsys):
    digest = approval.load_request(session)["diff_hash"]
    code, out, err = run_cli(monkeypatch, capsys, ["approve", str(session.directory), "--diff-hash", digest], tty=False)
    assert code == 0, err


def test_commit_refuses_while_a_decision_is_pending(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory)], typed="y\n")
    assert code == 1 and "lilguy approve" in err
    assert not (ws / "notes.txt").exists()


def test_commit_after_approval_then_undo(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    _approve(session, monkeypatch, capsys)
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory)], typed="y\n")
    assert code == 0, err
    assert "notes.txt" in out and str(ws) in out
    assert (ws / "notes.txt").read_text() == "x"
    assert (ws / "src" / "main.c").stat().st_mode & 0o777 == 0
    assert not session.directory.exists()  # layers discarded after commit
    audit = Path(session.cfg.state_dir) / "audit" / f"{session.directory.name}.jsonl"
    assert any(json.loads(line).get("decision") == "committed" for line in audit.read_text().splitlines())
    commit_id = next(word for word in out.split() if commitmod._COMMIT_ID_RE.match(word))

    code, out, err = run_cli(monkeypatch, capsys, ["undo", "--state-dir", str(session.cfg.state_dir)])
    assert code == 0 and commit_id in out  # listing
    code, out, err = run_cli(monkeypatch, capsys, ["undo", commit_id, "--state-dir", str(session.cfg.state_dir)],
                             typed="y\n")
    assert code == 0, err
    assert not (ws / "notes.txt").exists()
    assert (ws / "src" / "main.c").stat().st_mode & 0o777 == 0o644


def test_commit_answer_no_writes_nothing(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    _approve(session, monkeypatch, capsys)
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory)], typed="n\n")
    assert code == 1
    assert not (ws / "notes.txt").exists() and session.directory.exists()


def test_commit_without_terminal_needs_matching_hash(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    _approve(session, monkeypatch, capsys)
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory)], tty=False)
    assert code == 1 and "--diff-hash" in err
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory), "--diff-hash", "0" * 64],
                             tty=False)
    assert code == 1 and "differ" in err
    assert not (ws / "notes.txt").exists()
    digest = out.strip().splitlines()[-1].split()[-1]
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory), "--diff-hash", digest],
                             tty=False)
    assert code == 0, err
    assert (ws / "notes.txt").exists()


def test_commit_refuses_when_you_edited_the_same_file_meanwhile(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    _approve(session, monkeypatch, capsys)
    (ws / "src" / "main.c").write_text("my edit\n")
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory)], typed="y\n")
    assert code == 1 and "src/main.c" in err
    assert (ws / "src" / "main.c").read_text() == "my edit\n"
    assert not (ws / "notes.txt").exists()


def test_undo_refuses_after_later_edit(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    _approve(session, monkeypatch, capsys)
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory)], typed="y\n")
    commit_id = next(word for word in out.split() if commitmod._COMMIT_ID_RE.match(word))
    (ws / "notes.txt").write_text("kept")
    code, out, err = run_cli(monkeypatch, capsys, ["undo", commit_id, "--state-dir", str(session.cfg.state_dir)],
                             typed="y\n")
    assert code == 1 and "notes.txt" in err
    assert (ws / "notes.txt").read_text() == "kept"


def test_commit_first_recovers_an_interrupted_commit(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    _approve(session, monkeypatch, capsys)
    state = Path(session.cfg.state_dir)
    pre = commitmod._preimage(ws, PurePosixPath("half.txt"))
    (ws / "half.txt").write_text("written by a commit that crashed")
    journal_dir = state / "journal"
    journal_dir.mkdir(mode=0o700, exist_ok=True)
    (journal_dir / "1-0123456789ab.json").write_text(json.dumps({
        "commit_id": "1-0123456789ab", "workspace": str(ws), "status": "pending", "applied_index": 0,
        "entries": [{"op": "added", "path": "half.txt", "kind": "file"}], "preimages": {"half.txt": pre}}))
    code, out, err = run_cli(monkeypatch, capsys, ["commit", str(session.directory)], typed="y\n")
    assert code == 0, err
    assert "recovered" in (out + err).lower()
    assert not (ws / "half.txt").exists()
    assert not os.listdir(journal_dir)
