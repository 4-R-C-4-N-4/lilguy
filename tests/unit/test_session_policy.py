"""Pure lifecycle tests use a deterministic backend; actual containment tests are separate."""
from pathlib import Path

from lilguy.sandbox.backend import DiffEntry, RunSpec, Session, SessionConfig, StepResult


class FixtureBackend:
    """Deterministic backend. `queue` holds (step_entries, session_entries) applied on each run."""

    def __init__(self, entries, sources=None):
        self.entries = entries
        self.queue = []
        self.calls = 0
        self.rollbacks = 0
        self.sources = sources

    def run(self, session, spec):
        self.calls += 1
        session.uppers.append(Path(f"layer{self.calls}"))
        if self.queue:
            step, self.entries = self.queue.pop(0)
        else:
            step = self.entries
        return StepResult(0, "", "", ".", [], step, 1)

    def session_diff(self, session):
        return self.entries

    def resolve(self, session, rel):
        if self.sources is None:
            return None
        path = self.sources / rel.replace("/", "__")
        if not path.exists():
            path.write_text(f"content of {rel}")
        return path

    def rollback_step(self, session):
        self.rollbacks += 1
        session.uppers.pop()

    def discard(self, session):
        session.closed = True


def test_pending_freezes_further_execution(tmp_path):
    from lilguy.policy.session import GuardedSession
    directory = tmp_path / "state"
    directory.mkdir()
    session = Session(tmp_path / "workspace", directory, SessionConfig())
    backend = FixtureBackend([DiffEntry("deleted", "src/a", "file")])
    guarded = GuardedSession(backend, session)
    outcome = guarded.run(RunSpec(shell="unused"))
    assert outcome.decision.kind == "pending"
    outcome = guarded.run(RunSpec(shell="unused"))
    assert "SESSION_PENDING" in outcome.result.tags
    assert backend.calls == 1
    assert (directory / "approval-request.json").exists()
    guarded.discard()
    assert session.closed


def test_approval_record_rejects_stale_diff(tmp_path):
    from lilguy.policy.approval import approve
    from lilguy.policy.commit import ApprovalMismatch
    import json
    import pytest
    session = Session(tmp_path / "ws", tmp_path / "state", SessionConfig())
    session.directory.mkdir()
    (session.directory / "approval-request.json").write_text(json.dumps({"diff_hash": "old", "summary": "test"}))
    with pytest.raises(ApprovalMismatch):
        approve(session, "old", diff_fn=lambda _: [], resolve_fn=lambda *_: None)


def test_valid_human_approval_allows_next_step_but_is_consumed(tmp_path):
    from lilguy.policy.session import GuardedSession
    from lilguy.policy.approval import approve
    import json
    directory = tmp_path / "state"
    directory.mkdir()
    session = Session(tmp_path / "workspace", directory, SessionConfig())
    backend = FixtureBackend([DiffEntry("deleted", "src/a", "file")])
    guarded = GuardedSession(backend, session)
    guarded.run(RunSpec(shell="unused"))
    request = json.loads((directory / "approval-request.json").read_text())
    approve(session, request["diff_hash"], diff_fn=backend.session_diff, resolve_fn=backend.resolve)
    backend.entries = []  # next step has no risky effect
    # The existing view must still match at the time approval is consumed.
    backend.entries = [DiffEntry("deleted", "src/a", "file")]
    guarded.run(RunSpec(shell="unused"))
    assert backend.calls == 2
    assert not (directory / "approval.json").exists()


def test_workspace_policy_is_loaded_and_can_tighten_thresholds(tmp_path):
    from lilguy.policy.session import GuardedSession
    workspace = tmp_path / "workspace"
    (workspace / ".lilguy").mkdir(parents=True)
    (workspace / ".lilguy" / "policy.yaml").write_text("auto_commit:\n  max_bytes_written: 1\n")
    directory = tmp_path / "state"
    directory.mkdir()
    session = Session(workspace, directory, SessionConfig())
    backend = FixtureBackend([DiffEntry("modified", "a", "file", size_before=2, size_after=2)])
    # Use a real source only to bind the pending hash; execution remains the deterministic test backend.
    source = tmp_path / "upper-file"
    source.write_text("xy")
    backend.resolve = lambda *_: source
    assert GuardedSession(backend, session).run(RunSpec(shell="unused")).decision.rule == "max_bytes_written"


def test_workspace_policy_cannot_remove_mandatory_protection(tmp_path):
    from lilguy.policy.session import GuardedSession
    from lilguy.policy.engine import Policy
    directory = tmp_path / "state"
    directory.mkdir()
    session = Session(tmp_path / "workspace", directory, SessionConfig())
    backend = FixtureBackend([DiffEntry("added", ".env", "file")])
    guarded = GuardedSession(backend, session, policies=[Policy(protected=())])
    assert guarded.run(RunSpec(shell="unused")).decision.kind == "reject"


def test_uninspectable_effects_are_rejected_not_reported_policy_ok(tmp_path):
    from lilguy.policy.session import GuardedSession
    directory = tmp_path / "state"
    directory.mkdir()
    session = Session(tmp_path / "workspace", directory, SessionConfig())
    backend = FixtureBackend([])
    backend.run = lambda *_: StepResult(125, "", "cannot inspect", ".", ["DIFF_ERROR"], [], 1)
    assert GuardedSession(backend, session).run(RunSpec(shell="unused")).decision.kind == "reject"


def _approve_pending(directory, session, backend):
    import json
    from lilguy.policy.approval import approve
    request = json.loads((directory / "approval-request.json").read_text())
    approve(session, request["diff_hash"], diff_fn=backend.session_diff, resolve_fn=backend.resolve)


def _fixture(tmp_path, entries):
    from lilguy.policy.session import GuardedSession
    directory = tmp_path / "state"
    directory.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir()
    session = Session(tmp_path / "workspace", directory, SessionConfig())
    backend = FixtureBackend(entries, sources)
    return directory, session, backend, GuardedSession(backend, session)


def test_approved_changes_are_not_asked_about_again(tmp_path):
    deletion = DiffEntry("deleted", "src/a", "file", size_before=3)
    directory, session, backend, guarded = _fixture(tmp_path, [deletion])
    assert guarded.run(RunSpec(shell="unused")).decision.kind == "pending"
    _approve_pending(directory, session, backend)
    # Next step is harmless; the approved deletion is still in the session diff.
    note = DiffEntry("added", "notes.txt", "file", size_after=2)
    backend.queue = [([note], [deletion, note])]
    outcome = guarded.run(RunSpec(shell="unused"))
    assert outcome.decision.kind == "ok", outcome.decision
    assert backend.calls == 2


def test_new_risky_change_after_approval_is_still_caught(tmp_path):
    first = DiffEntry("deleted", "src/a", "file", size_before=3)
    directory, session, backend, guarded = _fixture(tmp_path, [first])
    guarded.run(RunSpec(shell="unused"))
    _approve_pending(directory, session, backend)
    second = DiffEntry("deleted", "src/b", "file", size_before=3)
    backend.queue = [([second], [first, second])]
    outcome = guarded.run(RunSpec(shell="unused"))
    assert outcome.decision.kind == "pending"
    assert outcome.decision.detail == "src/b"


def test_approved_entry_that_changes_again_is_reevaluated(tmp_path):
    chmod = DiffEntry("meta", "run.sh", "file", size_before=1, size_after=1, mode_before=0o644, mode_after=0o755)
    directory, session, backend, guarded = _fixture(tmp_path, [chmod])
    assert guarded.run(RunSpec(shell="unused")).decision.rule == "mode_change"
    _approve_pending(directory, session, backend)
    again = DiffEntry("meta", "run.sh", "file", size_before=1, size_after=1, mode_before=0o644, mode_after=0o000)
    backend.queue = [([again], [again])]
    assert guarded.run(RunSpec(shell="unused")).decision.kind == "pending"


def test_approved_file_whose_content_changes_is_reevaluated(tmp_path):
    big = DiffEntry("modified", "data.bin", "file", size_before=1, size_after=60_000_000)
    directory, session, backend, guarded = _fixture(tmp_path, [big])
    assert guarded.run(RunSpec(shell="unused")).decision.rule == "max_bytes_written"
    _approve_pending(directory, session, backend)
    # Same metadata, different bytes: the old approval must not cover it.
    (backend.sources / "data.bin").write_text("rewritten by a later step")
    backend.queue = [([big], [big])]
    assert guarded.run(RunSpec(shell="unused")).decision.kind == "pending"


def test_stopped_step_keeps_partial_work_as_pending(tmp_path):
    partial = DiffEntry("added", "build/out.o", "file", size_after=4)
    directory, session, backend, guarded = _fixture(tmp_path, [partial])
    backend.run = lambda s, spec: (s.uppers.append(Path("layer")) or
                                   StepResult(124, "", "", ".", ["STALLED"], [partial], 1))
    outcome = guarded.run(RunSpec(shell="unused"))
    assert outcome.decision.kind == "pending"
    assert outcome.decision.rule == "incomplete_step"
    assert backend.rollbacks == 0 and len(session.uppers) == 1
    import json
    request = json.loads((directory / "approval-request.json").read_text())
    assert request["stopped"] == ["STALLED"]


def test_stopped_step_touching_protected_path_is_still_rejected(tmp_path):
    bad = DiffEntry("modified", ".git/config", "file", size_after=4)
    directory, session, backend, guarded = _fixture(tmp_path, [bad])
    backend.run = lambda s, spec: (s.uppers.append(Path("layer")) or
                                   StepResult(124, "", "", ".", ["TIMEOUT"], [bad], 1))
    outcome = guarded.run(RunSpec(shell="unused"))
    assert outcome.decision.kind == "reject"
    assert backend.rollbacks == 1


def test_request_lists_changes_for_a_human(tmp_path):
    import json
    chmod = DiffEntry("meta", "src/main.c", "file", size_before=5, size_after=5, mode_before=0o644, mode_after=0)
    directory, session, backend, guarded = _fixture(tmp_path, [chmod])
    assert guarded.run(RunSpec(shell="unused")).decision.rule == "permission_reduction"
    request = json.loads((directory / "approval-request.json").read_text())
    change = request["changes"][0]
    assert change["path"] == "src/main.c" and change["mode_before"] == 0o644 and change["mode_after"] == 0
    assert request["new_paths"] == ["src/main.c"]


def test_rejected_step_rolls_back_and_is_audited(tmp_path):
    from lilguy.policy.session import GuardedSession
    directory = tmp_path / "state"
    directory.mkdir()
    session = Session(tmp_path / "workspace", directory, SessionConfig())
    backend = FixtureBackend([DiffEntry("modified", ".git/config", "file")])
    guarded = GuardedSession(backend, session)
    outcome = guarded.run(RunSpec(shell="unused"))
    assert outcome.decision.kind == "reject"
    assert backend.rollbacks == 1
    assert session.uppers == []
    assert '"decision": "reject"' in (directory / "audit.jsonl").read_text()


def test_typed_literals_are_not_persisted_in_audit_or_approval_request(tmp_path):
    import json

    change = DiffEntry("modified", "fixture.txt", "file", size_before=8, size_after=0)
    directory, session, backend, guarded = _fixture(tmp_path, [change])
    outcome = guarded.run(RunSpec(argv=["unused", "fixture-sensitive-text"]), typed_tool="fs.edit")
    assert outcome.decision.kind == "pending"
    request = json.loads((directory / "approval-request.json").read_text())
    audit = (directory / "audit.jsonl").read_text()
    assert request["command"] == {"tool": "fs.edit"}
    assert "fixture-sensitive-text" not in json.dumps(request)
    assert "fixture-sensitive-text" not in audit
