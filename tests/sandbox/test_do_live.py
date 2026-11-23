"""Live sandbox exercise of `lilguy do`, end to end, through the real guarded MCP server.

Three scenarios on fresh disposable fixtures, mirroring tests/sandbox/test_loop_live.py but
through do.py's own driver (do.drive / do.main), proving the whole stack it owns: the
model-prompt loop, the guarded-MCP-only call_tool, the versioned private record, and the
ground-truth pending/diff handoff.

Only the model's HTTP boundary (`do._chat_complete`) is stubbed with a scripted reply list --
conftest.py forbids real sockets in tests, and no model server is assumed to be running. The
sandbox, the session, the record and the handoff are all exercised for real.

Only harmless, disposable fixture content; no attack/bypass samples.
"""
from __future__ import annotations

import json

import pytest

from lilguy import do

pytestmark = pytest.mark.sandbox


def _script(monkeypatch, replies):
    it = iter(replies)

    def fake_complete(url, model, messages, grammar, timeout):
        try:
            return next(it)
        except StopIteration:
            return "done"
    monkeypatch.setattr(do, "_chat_complete", fake_complete)


def _state_and_workspace(tmp_path, name, fixture_files):
    workspace = tmp_path / name / "workspace"
    workspace.mkdir(parents=True)
    state = tmp_path / name / "state"
    for rel, text in fixture_files.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return workspace, state


# --- edit: done, staged, and the private record + handoff both verify it -------------------

def test_do_edit_stages_the_change_records_it_and_hands_off_cleanly(tmp_path, monkeypatch):
    workspace, state = _state_and_workspace(tmp_path, "edit", {"notes.txt": "status: draft\n"})
    _script(monkeypatch, [
        "tool fs.edit\npath: notes.txt\nold: status: draft\nnew: status: ready",
        "done",
    ])
    record, session_dir = do.drive("change status to ready", workspace, state, skip_preflight=True)

    assert record.terminal == "done"
    assert record.answer == ""
    assert len(record.turns) == 1
    assert "policy: ok" in record.turns[0].observation

    # the original workspace file is untouched until a human commits
    assert (workspace / "notes.txt").read_text() == "status: draft\n"

    # the record is persisted privately, outside the workspace, versioned
    path = do.save_record(state, session_dir.name, "change status to ready", workspace, record)
    assert path.is_relative_to(state)
    assert not path.is_relative_to(workspace)
    loaded = do.load_record(path)
    assert loaded["terminal"] == "done" and loaded["answer"] == "" and loaded["mode"] == "do"

    # the handoff is derived from the session's own ground truth, not the model's claim
    handoff = do.describe_handoff(session_dir)
    assert "notes.txt" in handoff
    assert "lilguy diff" in handoff and "lilguy commit" in handoff
    assert "WAITING FOR YOUR DECISION" not in handoff  # no approval threshold was crossed


def test_do_edit_replays_to_a_matching_record_and_staged_effect(tmp_path, monkeypatch):
    lines = [
        "tool fs.edit\npath: notes.txt\nold: status: draft\nnew: status: ready",
        "done",
    ]
    results = []
    for i in range(2):
        workspace, state = _state_and_workspace(tmp_path, f"edit-replay-{i}", {"notes.txt": "status: draft\n"})
        _script(monkeypatch, list(lines))
        results.append(do.drive("change status to ready", workspace, state, skip_preflight=True))
    (r1, s1), (r2, s2) = results
    assert r1.terminal == r2.terminal == "done"
    assert r1.answer == r2.answer
    assert [t.observation for t in r1.turns] == [t.observation for t in r2.turns]


# --- ask: terminal, nothing staged, handoff says so -----------------------------------------

def test_do_ask_is_terminal_with_nothing_staged(tmp_path, monkeypatch):
    workspace, state = _state_and_workspace(
        tmp_path, "ask", {"config/a.yaml": "timeout: 10\n", "config/b.yaml": "timeout: 10\n"})
    _script(monkeypatch, ["ask\nthere are two config files; which one did you mean?"])
    record, session_dir = do.drive("set the timeout to 30", workspace, state, skip_preflight=True)

    assert record.terminal == "ask"
    assert record.answer == "there are two config files; which one did you mean?"
    assert record.turns == ()
    assert do.describe_handoff(session_dir) == (
        "Nothing staged; the trajectory never opened a sandbox session. Nothing to review or commit.")


# --- pending: approval handoff matches the real, ground-truth session state ----------------

def test_do_pending_policy_surfaces_the_real_approval_handoff(tmp_path, monkeypatch):
    workspace, state = _state_and_workspace(tmp_path, "pending", {"notes.txt": "todo: ship\nstatus: draft\n"})
    _script(monkeypatch, [
        "run\ncp /dev/null notes.txt",
        "done",
    ])
    record, session_dir = do.drive("clear out notes.txt", workspace, state, skip_preflight=True)

    assert record.terminal == "done"
    assert len(record.turns) == 1
    assert "policy: pending" in record.turns[0].observation
    assert record.turns[0].is_error

    handoff = do.describe_handoff(session_dir)
    assert "WAITING FOR YOUR DECISION" in handoff
    assert "lilguy commit" in handoff and "approves and writes" in handoff and "lilguy deny" in handoff
    assert "notes.txt" in handoff

    # and the handoff is ground truth, verifiable independently via the existing CLI:
    from lilguy.policy import approval
    with session_dir.joinpath("meta.json").open():
        pass
    from lilguy.sandbox import persist
    with persist.session_lock(session_dir, wait=False):
        session = persist.load_session(session_dir)
        assert (session_dir / approval.REQUEST).exists()
        assert approval.load_request(session)["diff_hash"] in handoff


def test_do_fails_closed_if_the_model_ignores_a_pending_handoff(tmp_path, monkeypatch):
    """Mirrors test_loop_live's fail-closed check: through do.py's own call_tool/driver, a
    script that tries another `run` after a pending observation must still be forced to
    `invalid`, never silently continuing or getting a false 'ok' handoff."""
    workspace, state = _state_and_workspace(tmp_path, "pending-bad", {"notes.txt": "todo: ship\nstatus: draft\n"})
    _script(monkeypatch, [
        "run\ncp /dev/null notes.txt",
        "run\necho should-not-run > extra.txt",
    ])
    record, session_dir = do.drive("clear out notes.txt", workspace, state, skip_preflight=True)
    assert record.terminal == "invalid"
    assert record.answer is None
    assert len(record.turns) == 1
    handoff = do.describe_handoff(session_dir)
    assert "extra.txt" not in handoff
    assert "WAITING FOR YOUR DECISION" in handoff


# --- the guarded server never exposes approval authority to the model ----------------------

def test_do_never_sees_approval_tools_from_the_guarded_server(tmp_path, monkeypatch):
    from lilguy.mcp_server import build_v1_tools
    served = set(build_v1_tools())
    assert served.isdisjoint(do._FORBIDDEN_MODEL_TOOLS)


# --- CLI end to end, exercised on a benign fixture, with preflight stubbed -----------------

# An explicit URL keeps these on the stubbed model boundary, never the user's `lilguy setup`.
STUB_URL = "http://127.0.0.1:1"


def test_cli_do_main_prints_the_handoff_and_saves_the_record(tmp_path, monkeypatch, capsys):
    workspace, state = _state_and_workspace(tmp_path, "cli", {"notes.txt": "status: draft\n"})
    monkeypatch.setattr(do, "check_sandbox", lambda: None)
    monkeypatch.setattr(do, "check_model", lambda url, timeout=5.0: None)
    _script(monkeypatch, [
        "tool fs.edit\npath: notes.txt\nold: status: draft\nnew: status: ready",
        "done",
    ])
    code = do.main(["change status to ready", "--workspace", str(workspace), "--state-dir", str(state),
                     "--url", STUB_URL])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("[done]\n")  # v3: no model summary at all
    assert "fs.edit path=notes.txt old=<13 chars> new=<13 chars>" in out
    plan = out.split("Changed contents")[0]
    assert "status: draft" not in plan  # typed edit literals are not kept in the audit log
    assert "-status: draft" in out and "+status: ready" in out  # the content diff shows them
    assert "Record saved:" in out
    assert "lilguy diff" in out
    records = list((state / "records").glob("*.json"))
    assert len(records) == 1
    saved = json.loads(records[0].read_text())
    assert saved["terminal"] == "done" and saved["schema_version"] == do.RECORD_SCHEMA_VERSION


def test_cli_ask_quotes_the_last_output(tmp_path, monkeypatch, capsys):
    workspace, state = _state_and_workspace(tmp_path, "ask", {"access.log": "GET /\nGET /about\nPOST /x\n"})
    monkeypatch.setattr(do, "check_sandbox", lambda: None)
    monkeypatch.setattr(do, "check_model", lambda url, timeout=5.0: None)
    _script(monkeypatch, ["tool fs.read\npath: access.log", "run\nwc -l < access.log", "done"])
    code = do.ask_main(["How many lines are in access.log?", "--workspace", str(workspace), "--state-dir", str(state),
                     "--url", STUB_URL])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("Answer (output of `wc -l < access.log`, exit 0):\n  3\n")
    assert "Nothing staged" in out
    assert json.loads(next((state / "records").glob("*.json")).read_text())["mode"] == "ask"


def test_cli_ask_refuses_a_write_and_shows_no_answer(tmp_path, monkeypatch, capsys):
    workspace, state = _state_and_workspace(tmp_path, "askw", {"access.log": "GET /\nGET /about\nPOST /x\n"})
    monkeypatch.setattr(do, "check_sandbox", lambda: None)
    monkeypatch.setattr(do, "check_model", lambda url, timeout=5.0: None)
    _script(monkeypatch, ["run\nwc -l < access.log > count.txt", "done"])
    code = do.ask_main(["How many lines are in access.log?", "--workspace", str(workspace), "--state-dir", str(state),
                     "--url", STUB_URL])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("No answer: the model did not finish with a command that lilguy let stand")
    assert "Nothing staged" in out
    assert sorted(p.name for p in workspace.iterdir()) == ["access.log"]
    saved = json.loads(next((state / "records").glob("*.json")).read_text())
    assert "policy: rejected (read-only question: count.txt)" in saved["turns"][0]["observation"]
