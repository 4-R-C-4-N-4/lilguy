"""Live sandbox tests for the one-question apply after `lilguy do`, and for the review
commands defaulting to the latest session of the current folder.

The model is scripted at its HTTP boundary (as in test_do_live.py); the sandbox, sessions,
approval and the journaled commit are all real. Only harmless fixture content.
"""
from __future__ import annotations

import io
import sys

import pytest

from lilguy import do
from lilguy.policy import cli as decision_cli

pytestmark = pytest.mark.sandbox


def _script(monkeypatch, replies):
    it = iter(replies)
    monkeypatch.setattr(do, "_chat_complete", lambda *a, **k: next(it, "done"))


def _workspace(tmp_path, files):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for rel, text in files.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return workspace, tmp_path / "state"


def _drive(request, workspace, state):
    _record, session = do.drive(request, workspace, state, skip_preflight=True)
    assert session is not None
    return session


def _answer(monkeypatch, text):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


EDIT = ["tool fs.edit\npath: notes.txt\nold: status: draft\nnew: status: ready", "done"]


def test_yes_applies_the_shown_change(tmp_path, monkeypatch, capfd):
    workspace, state = _workspace(tmp_path, {"notes.txt": "status: draft\n"})
    _script(monkeypatch, EDIT)
    session = _drive("change status to ready", workspace, state)
    _answer(monkeypatch, "y\n")
    assert decision_cli.apply_now(session) == 0
    assert (workspace / "notes.txt").read_text() == "status: ready\n"
    out = capfd.readouterr().out
    assert "Apply this change to" in out and "Undo with: lilguy undo" in out
    assert not session.exists()  # committed sessions are discarded


def test_anything_but_yes_leaves_it_staged(tmp_path, monkeypatch, capfd):
    workspace, state = _workspace(tmp_path, {"notes.txt": "status: draft\n"})
    _script(monkeypatch, EDIT)
    session = _drive("change status to ready", workspace, state)
    _answer(monkeypatch, "\n")
    assert decision_cli.apply_now(session) == 1
    assert (workspace / "notes.txt").read_text() == "status: draft\n"
    assert "the changes stay staged" in capfd.readouterr().out
    assert session.exists()


def test_yes_on_an_approval_threshold_approves_and_applies_in_one_step(tmp_path, monkeypatch, capfd):
    workspace, state = _workspace(tmp_path, {"old.log": "x\n", "keep.txt": "k\n"})
    _script(monkeypatch, ["run\nrm old.log", "done"])
    session = _drive("delete old.log", workspace, state)
    assert (session / "approval-request.json").exists()
    _answer(monkeypatch, "yes\n")
    assert decision_cli.apply_now(session) == 0
    assert not (workspace / "old.log").exists() and (workspace / "keep.txt").exists()
    assert "Approve and apply this change" in capfd.readouterr().out


def test_no_on_an_approval_threshold_changes_nothing(tmp_path, monkeypatch):
    workspace, state = _workspace(tmp_path, {"old.log": "x\n"})
    _script(monkeypatch, ["run\nrm old.log", "done"])
    session = _drive("delete old.log", workspace, state)
    _answer(monkeypatch, "n\n")
    assert decision_cli.apply_now(session) == 1
    assert (workspace / "old.log").read_text() == "x\n"
    assert not (session / "approval.json").exists()


def test_review_commands_default_to_the_latest_staged_session_here(tmp_path, monkeypatch, capfd):
    workspace, state = _workspace(tmp_path, {"notes.txt": "status: draft\n", "b.txt": "one\n"})
    _script(monkeypatch, EDIT)
    first = _drive("change status to ready", workspace, state)
    _script(monkeypatch, ["run\ncat b.txt"])  # a later session that stages nothing
    _drive("show b.txt", workspace, state)
    assert decision_cli.latest_session(state, workspace) == first
    monkeypatch.chdir(workspace)
    assert decision_cli.diff_main(["--state-dir", str(state)]) == 0
    assert "+status: ready" in capfd.readouterr().out
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    assert decision_cli.diff_main(["--state-dir", str(state)]) == 1
    assert "no session with staged changes" in capfd.readouterr().err


def test_handoff_prints_short_commands_from_the_workspace(tmp_path, monkeypatch):
    workspace, state = _workspace(tmp_path, {"notes.txt": "status: draft\n"})
    _script(monkeypatch, EDIT)
    session = _drive("change status to ready", workspace, state)
    monkeypatch.chdir(workspace)
    assert do.describe_handoff(session).endswith("Review: lilguy diff\nCommit: lilguy commit")
    monkeypatch.chdir(tmp_path)
    assert f"Commit: lilguy commit {session}" in do.describe_handoff(session)


def test_later_commit_of_a_pending_change_approves_and_writes_with_one_hash(tmp_path, monkeypatch, capfd):
    workspace, state = _workspace(tmp_path, {"old.log": "x\n"})
    _script(monkeypatch, ["run\nrm old.log", "done"])
    session = _drive("delete old.log", workspace, state)
    # Without a terminal the hash is the confirmation; showing it first changes nothing.
    assert decision_cli.commit_main([str(session)]) == 1
    out = capfd.readouterr().out
    assert "Needs approval because" in out and (workspace / "old.log").exists()
    digest = next(line.split()[2] for line in out.splitlines() if line.startswith("Diff hash"))
    assert decision_cli.commit_main([str(session), "--diff-hash", "0" * 64]) == 1
    assert (workspace / "old.log").exists()
    assert decision_cli.commit_main([str(session), "--diff-hash", digest]) == 0
    assert not (workspace / "old.log").exists()
