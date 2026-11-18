"""Independent regression for a mutation occurring before progress persistence."""
import pytest

from lilguy.policy import commit as module
from lilguy.sandbox.backend import DiffEntry, Session, SessionConfig


def test_standalone_commit_cannot_bypass_workspace_policy(tmp_path):
    ws, upper, state = (tmp_path / n for n in ("ws", "upper", "state"))
    for path in (ws, upper, state):
        path.mkdir()
    (ws / ".lilguy").mkdir()
    (ws / ".lilguy" / "policy.yaml").write_text("auto_commit:\n  max_bytes_written: 1\n")
    session = Session(ws, tmp_path / "session", SessionConfig(state_dir=state))
    session.directory.mkdir()
    module.save_snapshot(session.directory, module.capture_snapshot(ws))
    (upper / "a").write_text("xy")
    with pytest.raises(module.ApprovalRequired):
        module.commit(session, diff_fn=lambda _: [DiffEntry("added", "a", "file", size_after=2)],
                      resolve_fn=lambda _, rel: upper / rel)
    assert not (ws / "a").exists()


@pytest.mark.parametrize("mutation", ["add", "modify", "delete"])
def test_deep_external_change_under_replaced_directory_is_a_conflict(tmp_path, mutation):
    ws, upper, state = (tmp_path / n for n in ("ws", "upper", "state"))
    for path in (ws, upper, state):
        path.mkdir()
    (ws / "d" / "sub").mkdir(parents=True)
    (ws / "d" / "sub" / "old").write_text("old")
    session = Session(ws, tmp_path / "session", SessionConfig(state_dir=state))
    session.directory.mkdir()
    module.save_snapshot(session.directory, module.capture_snapshot(ws))
    if mutation == "add":
        (ws / "d" / "sub" / "human-edit").write_text("must survive")
    elif mutation == "modify":
        (ws / "d" / "sub" / "old").write_text("human modification")
    else:
        (ws / "d" / "sub" / "old").unlink()
    before = {p.relative_to(ws).as_posix(): p.read_text() for p in ws.rglob("*") if p.is_file()}
    (upper / "d").write_text("replacement")
    with pytest.raises(module.ApprovalRequired) as error:
        module.commit(session, diff_fn=lambda _: [DiffEntry("replaced_dir", "d", "file", size_after=11)],
                      resolve_fn=lambda _, rel: upper / rel)
    assert error.value.decision.rule == "conflict"
    after = {p.relative_to(ws).as_posix(): p.read_text() for p in ws.rglob("*") if p.is_file()}
    assert after == before


def _approved_session(tmp_path):
    ws, upper, state = (tmp_path / n for n in ("ws", "upper", "state"))
    for path in (ws, upper, state):
        path.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "a").write_text("old")
    session = Session(ws, tmp_path / "session", SessionConfig(state_dir=state))
    session.directory.mkdir()
    module.save_snapshot(session.directory, module.capture_snapshot(ws))
    deletion = DiffEntry("deleted", "src/a", "file", size_before=3)
    resolve = lambda _, rel: upper / rel  # noqa: E731
    module.add_approved_fingerprints(session.directory, {module.entry_fingerprint(deletion, session, resolve)})
    return ws, upper, session, deletion, resolve


def test_commit_honours_changes_already_approved_in_the_session(tmp_path):
    ws, upper, session, deletion, resolve = _approved_session(tmp_path)
    module.commit(session, diff_fn=lambda _: [deletion], resolve_fn=resolve)
    assert not (ws / "src" / "a").exists()


def test_commit_still_requires_approval_for_unapproved_extras(tmp_path):
    ws, upper, session, deletion, resolve = _approved_session(tmp_path)
    (ws / "src" / "b").write_text("other")
    module.save_snapshot(session.directory, module.capture_snapshot(ws))
    extra = DiffEntry("deleted", "src/b", "file", size_before=5)
    with pytest.raises(module.ApprovalRequired):
        module.commit(session, diff_fn=lambda _: [deletion, extra], resolve_fn=resolve)
    assert (ws / "src" / "a").exists() and (ws / "src" / "b").exists()


def test_baseline_never_excuses_a_conflict(tmp_path):
    ws, upper, session, deletion, resolve = _approved_session(tmp_path)
    (ws / "src" / "a").write_text("human edited after the session opened")
    with pytest.raises(module.ApprovalRequired) as error:
        module.commit(session, diff_fn=lambda _: [deletion], resolve_fn=resolve)
    assert error.value.decision.rule == "conflict"


def test_exception_after_apply_restores_attempted_operation(tmp_path, monkeypatch):
    ws, upper, state = (tmp_path / n for n in ("ws", "upper", "state"))
    for path in (ws, upper, state):
        path.mkdir()
    (ws / "a").write_text("old")
    (upper / "a").write_text("new")
    session = Session(ws, tmp_path / "session", SessionConfig(state_dir=state))
    session.directory.mkdir()
    module.save_snapshot(session.directory, module.capture_snapshot(ws))
    original = module._apply_one
    def fail_after_apply(*args):
        original(*args)
        raise OSError("injected after fs mutation before progress record")
    monkeypatch.setattr(module, "_apply_one", fail_after_apply)
    with pytest.raises(OSError):
        module.commit(session, diff_fn=lambda _: [DiffEntry("modified", "a", "file", size_before=3, size_after=3)],
                      resolve_fn=lambda _, rel: upper / rel, snapshot=module.capture_snapshot(ws))
    assert (ws / "a").read_text() == "old"
