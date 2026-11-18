"""`lilguy sessions`: list kept sessions; prune idle ones only when asked."""
import os
import threading
import time

from lilguy.sandbox import persist
from tests.unit.test_decision_cli import run_cli
from tests.unit.test_human_approval import pending  # noqa: F401  (fixture)


def _age(session_dir, days):
    old = time.time() - days * 86400
    for name in ("progress.json", "audit.jsonl", "meta.json", "config.json",
                 "approval-request.json", "approval.json"):
        path = session_dir / name
        if path.exists():
            os.utime(path, (old, old))


def test_lists_kept_sessions(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    code, out, err = run_cli(monkeypatch, capsys, ["sessions", "--state-dir", str(session.cfg.state_dir)])
    assert code == 0, err
    assert session.directory.name in out and str(ws) in out
    assert "waiting for approval" in out


def test_prune_removes_only_idle_sessions(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    state = session.cfg.state_dir
    code, out, err = run_cli(monkeypatch, capsys, ["sessions", "--state-dir", str(state), "--prune", "14"])
    assert code == 0 and session.directory.exists()  # fresh: kept
    _age(session.directory, 20)
    code, out, err = run_cli(monkeypatch, capsys, ["sessions", "--state-dir", str(state), "--prune", "14"])
    assert code == 0, err
    assert not session.directory.exists()
    assert session.directory.name in out
    assert (ws / "src" / "main.c").read_text() == "int main(){}\n"  # workspace untouched


def test_prune_skips_a_session_in_use(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    _age(session.directory, 20)
    held, release = threading.Event(), threading.Event()

    def hold():
        with persist.session_lock(session.directory):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    held.wait(5)
    try:
        code, out, err = run_cli(monkeypatch, capsys,
                                 ["sessions", "--state-dir", str(session.cfg.state_dir), "--prune", "14"])
    finally:
        release.set()
        thread.join()
    assert session.directory.exists()
    assert "in use" in out + err


def test_prune_ignores_things_that_are_not_sessions(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state"
    (state / "journal").mkdir(parents=True)
    (state / "notes").mkdir()
    (state / "1-0123456789abcdef").mkdir()  # looks like a session id but has no meta.json
    for path in state.iterdir():
        os.utime(path, (0, 0))
    code, out, err = run_cli(monkeypatch, capsys, ["sessions", "--state-dir", str(state), "--prune", "1"])
    assert code == 0
    assert sorted(p.name for p in state.iterdir()) == ["1-0123456789abcdef", "journal", "notes"]
