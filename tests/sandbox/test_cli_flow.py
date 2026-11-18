"""End to end through the real sandbox: keep -> pending -> diff -> approve -> continue; and deny."""
import io
import json

import pytest

from lilguy import cli

pytestmark = pytest.mark.sandbox


class Terminal(io.StringIO):
    def isatty(self):
        return False


def lilguy(monkeypatch, capsys, *argv):
    monkeypatch.setattr("sys.stdin", Terminal(""))
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def project(tmp_path):
    ws = tmp_path / "project"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "main.c").write_text("int main(){}\n")
    (ws / "src" / "main.c").chmod(0o644)
    return ws, tmp_path / "state"


def _start_pending(monkeypatch, capsys, ws, state):
    code, out, err = lilguy(monkeypatch, capsys, "sandbox-run", "--workspace", str(ws), "--state-dir", str(state),
                            "--keep", "--cmd", "chmod 000 src/main.c")
    assert code == 2, err
    result = json.loads(out)
    assert result["policy"]["rule"] == "permission_reduction"
    assert "lilguy approve" in err
    return result["session_path"]


def test_keep_review_approve_and_continue(project, monkeypatch, capsys):
    ws, state = project
    session = _start_pending(monkeypatch, capsys, ws, state)
    # Frozen until a human decides.
    code, out, err = lilguy(monkeypatch, capsys, "sandbox-run", "--session", session, "--cmd", "true")
    assert code == 2 and "SESSION_PENDING" in out
    code, out, err = lilguy(monkeypatch, capsys, "diff", session)
    assert code == 0 and "644 -> 000" in out
    digest = out.strip().splitlines()[-1].split()[-1]
    code, out, err = lilguy(monkeypatch, capsys, "approve", session, "--diff-hash", digest)
    assert code == 0, err
    code, out, err = lilguy(monkeypatch, capsys, "sandbox-run", "--session", session, "--cmd", "echo hi > notes.txt")
    assert code == 0, err
    assert json.loads(out)["policy"]["kind"] == "ok"  # the approved chmod is not asked about again
    assert (ws / "src" / "main.c").stat().st_mode & 0o777 == 0o644  # nothing committed
    assert not (ws / "notes.txt").exists()


def test_deny_rolls_back_then_session_continues(project, monkeypatch, capsys):
    ws, state = project
    session = _start_pending(monkeypatch, capsys, ws, state)
    code, out, err = lilguy(monkeypatch, capsys, "deny", session)
    assert code == 0 and "src/main.c" in out
    code, out, err = lilguy(monkeypatch, capsys, "sandbox-run", "--session", session,
                            "--cmd", "stat -c %a src/main.c")
    assert code == 0, err
    assert json.loads(out)["result"]["stdout"].strip() == "644"


def test_preview_without_keep_discards_pending_work(project, monkeypatch, capsys):
    ws, state = project
    code, out, err = lilguy(monkeypatch, capsys, "sandbox-run", "--workspace", str(ws), "--state-dir", str(state),
                            "--cmd", "chmod 000 src/main.c")
    assert code == 2 and "--keep" in err
    assert json.loads(out)["session"] is None
    assert not any(state.iterdir())


def test_full_path_to_the_real_workspace_and_back(project, monkeypatch, capsys):
    ws, state = project
    session = _start_pending(monkeypatch, capsys, ws, state)
    code, out, err = lilguy(monkeypatch, capsys, "diff", session)
    digest = out.strip().splitlines()[-1].split()[-1]
    assert lilguy(monkeypatch, capsys, "approve", session, "--diff-hash", digest)[0] == 0
    code, out, err = lilguy(monkeypatch, capsys, "sandbox-run", "--session", session,
                            "--cmd", "mkdir -p docs && echo hello > docs/readme.txt")
    assert code == 0, err
    code, out, err = lilguy(monkeypatch, capsys, "commit", session)
    assert code == 1 and "--diff-hash" in err  # no terminal: must name the reviewed hash
    digest = out.strip().splitlines()[-1].split()[-1]
    code, out, err = lilguy(monkeypatch, capsys, "commit", session, "--diff-hash", digest)
    assert code == 0, err
    assert (ws / "docs" / "readme.txt").read_text() == "hello\n"
    assert (ws / "src" / "main.c").stat().st_mode & 0o777 == 0
    commit_id = out.split("Committed")[1].split()[3]

    code, out, err = lilguy(monkeypatch, capsys, "undo", "--state-dir", str(state))
    assert commit_id in out
    monkeypatch.setattr("sys.stdin", _Tty("y\n"))
    assert cli.main(["undo", commit_id, "--state-dir", str(state)]) == 0
    assert not (ws / "docs").exists()
    assert (ws / "src" / "main.c").stat().st_mode & 0o777 == 0o644


class _Tty(io.StringIO):
    def isatty(self):
        return True
