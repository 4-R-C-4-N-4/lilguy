"""`lilguy approve | deny | diff` as a human would use them from a second terminal."""
import io
import json

import pytest

from lilguy import cli
from lilguy.policy import approval
from lilguy.sandbox import persist
from tests.unit.test_human_approval import pending  # noqa: F401  (fixture)


class Terminal(io.StringIO):
    def __init__(self, text="", tty=True):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


def run_cli(monkeypatch, capsys, argv, typed="", tty=True):
    monkeypatch.setattr("sys.stdin", Terminal(typed, tty))
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def _ref(session):
    return str(session.directory)


def test_approve_shows_summary_and_needs_a_typed_yes(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, backend, guarded = pending
    code, out, err = run_cli(monkeypatch, capsys, ["approve", _ref(session)], typed="n\n")
    assert code == 1
    assert "644 -> 000" in out and "permission_reduction" in out
    assert not (session.directory / "approval.json").exists()
    code, out, err = run_cli(monkeypatch, capsys, ["approve", _ref(session)], typed="y\n")
    assert code == 0, err
    assert (session.directory / "approval.json").exists()
    assert "nothing has been written to your workspace" in out.lower()


def test_approve_refuses_non_interactive_without_hash(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    code, out, err = run_cli(monkeypatch, capsys, ["approve", _ref(session)], typed="y\n", tty=False)
    assert code == 1 and "--diff-hash" in err
    assert not (session.directory / "approval.json").exists()


def test_approve_by_reviewed_hash_without_terminal(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    digest = approval.load_request(session)["diff_hash"]
    code, out, err = run_cli(monkeypatch, capsys, ["approve", _ref(session), "--diff-hash", digest], tty=False)
    assert code == 0, err
    record = json.loads((session.directory / "approval.json").read_text())
    assert record["diff_hash"] == digest


def test_approve_with_wrong_hash_is_refused(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    code, out, err = run_cli(monkeypatch, capsys, ["approve", _ref(session), "--diff-hash", "0" * 64], tty=False)
    assert code == 1 and "differ" in err
    assert not (session.directory / "approval.json").exists()


def test_deny_rolls_back_and_reports(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    code, out, err = run_cli(monkeypatch, capsys, ["deny", _ref(session)])
    assert code == 0, err
    assert "src/main.c" in out
    assert len(persist.load_session(session.directory).uppers) == 1


def test_diff_shows_current_session_changes(pending, monkeypatch, capsys):  # noqa: F811
    ws, session, *_ = pending
    code, out, err = run_cli(monkeypatch, capsys, ["diff", _ref(session)])
    assert code == 0, err
    assert "notes.txt" in out and "src/main.c" in out


def test_unknown_session_is_a_clean_error(tmp_path, monkeypatch, capsys):
    code, out, err = run_cli(monkeypatch, capsys, ["deny", str(tmp_path / "nope")])
    assert code == 1 and "no such session" in err


def test_pointing_at_a_non_session_directory_creates_nothing(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "project"
    plain.mkdir(mode=0o700)
    code, out, err = run_cli(monkeypatch, capsys, ["deny", str(plain)])
    assert code == 1 and "not a lilguy session" in err
    assert list(plain.iterdir()) == []


@pytest.mark.parametrize("command", ["approve", "deny", "diff"])
def test_commands_listed_in_help(command, monkeypatch, capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert command in capsys.readouterr().out
