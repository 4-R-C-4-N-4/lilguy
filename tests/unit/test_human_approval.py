"""Human approve/deny flow on real layer directories and real diffs.

The step writer below stands in for bubblewrap: it writes into the new upper
layer the way the sandbox would. Live sandbox coverage is in tests/sandbox.
"""
import json
import os
import threading
import time

import pytest

from lilguy.policy import approval
from lilguy.policy.session import GuardedSession
from lilguy.sandbox import diff, layers, persist
from lilguy.sandbox.backend import RunSpec, SessionConfig, StepResult


class LayerWriter:
    """Backend whose 'commands' are Python callables writing into the new upper layer."""

    def __init__(self):
        self.actions = []
        self.hold = None

    def run(self, s, spec):
        upper = layers.new_layer(s)
        action, cwd = self.actions.pop(0)
        action(upper)
        if self.hold:
            self.hold.wait(5)
        s.cwd = cwd
        return StepResult(0, "", "", s.cwd, [], diff.step_diff(s, upper), 1)

    def session_diff(self, s):
        return diff.session_diff(s)

    def resolve(self, s, rel):
        return layers.resolve(s, rel)

    def rollback_step(self, s):
        layers.rollback_step(s)

    def discard(self, s):
        layers.discard(s)


def chmod_zero(upper):
    (upper / "src").mkdir()
    (upper / "src" / "main.c").write_text("int main(){}\n")
    os.chmod(upper / "src" / "main.c", 0)


def write(name, text="x"):
    def action(upper):
        (upper / name).write_text(text)
    return action


@pytest.fixture
def pending(tmp_path):
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "main.c").write_text("int main(){}\n")
    os.chmod(ws / "src" / "main.c", 0o644)
    session = layers.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    backend = LayerWriter()
    backend.actions = [(write("notes.txt"), "."), (chmod_zero, "src")]
    guarded = GuardedSession(backend, session)
    assert guarded.run(RunSpec(shell="echo notes > notes.txt")).decision.kind == "ok"
    outcome = guarded.run(RunSpec(shell="cd src && chmod 000 main.c"))
    assert outcome.decision.rule == "permission_reduction"
    return ws, session, backend, guarded


def test_summary_shows_permissions_and_what_needs_deciding(pending):
    ws, session, _, _ = pending
    text = approval.summarize(session)
    assert "permission_reduction" in text
    assert "src/main.c" in text and "644 -> 000" in text
    assert "notes.txt" in text
    assert "untrusted" in text  # the command was proposed by the model
    assert approval.load_request(session)["diff_hash"][:12] in text


def test_summary_neutralises_terminal_escapes_in_paths(pending, tmp_path):
    ws, session, backend, guarded = pending
    request = approval.load_request(session)
    request["changes"].append({"op": "added", "path": "evil\x1b[2J\x07.txt", "kind": "file",
                               "size_before": None, "size_after": 1, "mode_before": None,
                               "mode_after": 420, "symlink_target": None, "is_binary": False})
    (session.directory / "approval-request.json").write_text(json.dumps(request))
    text = approval.summarize(session)
    assert "\x1b" not in text and "\x07" not in text
    assert "evil\\x1b[2J\\x07.txt" in text


def test_approve_from_another_process_lets_the_session_continue(pending):
    ws, session, backend, guarded = pending
    with approval.decision_session(session.directory) as other:  # what `lilguy approve` does
        approval.approve(other, approval.load_request(other)["diff_hash"])
    backend.actions = [(write("more.txt"), "src")]
    assert guarded.run(RunSpec(shell="echo more > more.txt")).decision.kind == "ok"


def test_deny_rolls_back_only_the_step_that_asked(pending):
    ws, session, backend, guarded = pending
    with approval.decision_session(session.directory) as other:
        rolled_back = approval.deny(other)
    assert rolled_back == ["src/main.c"]
    reloaded = persist.load_session(session.directory)
    assert len(reloaded.uppers) == 1 and reloaded.cwd == "."
    assert layers.resolve(reloaded, "notes.txt") is not None
    assert not (session.directory / "approval-request.json").exists()
    audit = (session.directory / "audit.jsonl").read_text()
    assert '"decision": "denied"' in audit
    assert (ws / "src" / "main.c").stat().st_mode & 0o777 == 0o644


def test_live_process_refuses_to_continue_after_external_deny(pending):
    ws, session, backend, guarded = pending
    with approval.decision_session(session.directory) as other:
        approval.deny(other)
    outcome = guarded.run(RunSpec(shell="true"))
    assert "SESSION_CHANGED" in outcome.result.tags
    assert outcome.decision.kind == "reject"


def test_deny_discard_removes_the_session(pending):
    ws, session, backend, guarded = pending
    with approval.decision_session(session.directory) as other:
        approval.deny(other, discard=True)
    assert not session.directory.exists()
    assert (ws / "src" / "main.c").read_text() == "int main(){}\n"


def test_approve_and_deny_refuse_while_a_step_is_running(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    session = layers.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    backend = LayerWriter()
    backend.actions = [(write("a"), ".")]
    backend.hold = threading.Event()
    guarded = GuardedSession(backend, session)
    worker = threading.Thread(target=guarded.run, args=(RunSpec(shell="slow"),))
    worker.start()
    time.sleep(0.2)
    try:
        with pytest.raises(persist.SessionBusy):
            with approval.decision_session(session.directory) as other:
                approval.deny(other)
    finally:
        backend.hold.set()
        worker.join(5)


def test_nothing_to_approve_or_deny_is_an_error(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    session = layers.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    with pytest.raises(approval.CommitError):
        approval.deny(session)
    with pytest.raises(approval.CommitError):
        approval.summarize(session)
