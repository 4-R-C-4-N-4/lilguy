"""Tests for lilguy.policy.commit — journaled filesystem commit/undo/recover.

All fixtures live under TMPDIR scratch dirs provided by pytest's tmp_path;
no real project is ever touched. diff_fn/resolve_fn are faked here because
lilguy.sandbox.diff / lilguy.sandbox.layers may not have landed yet; commit()
accepts them as explicit overrides for exactly this reason.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from lilguy.policy import commit as commitmod
from lilguy.policy.commit import (
    ApprovalMismatch,
    ApprovalRequired,
    CommitError,
    PolicyRejected,
    capture_snapshot,
    commit,
    diff_hash,
    load_snapshot,
    recover,
    save_snapshot,
    undo,
)
from lilguy.policy.engine import Policy
from lilguy.sandbox.backend import DiffEntry, Session, SessionConfig


def make_session(workspace, upper, state_dir):
    cfg = SessionConfig(state_dir=state_dir)
    return Session(workspace=workspace, directory=upper, cfg=cfg)


def open_session(workspace, upper, state_dir):
    """Mirror the real flow: capture + save a conflict-detection snapshot
    under the session's own directory AT session-creation time (never after
    external mutations), the way layers.open_session is expected to.
    """
    session = make_session(workspace, upper, state_dir)
    save_snapshot(session.directory, capture_snapshot(workspace))
    return session


def upper_resolve(upper_dir):
    def resolve_fn(session, rel):
        p = upper_dir / rel
        return p if p.exists() else None
    return resolve_fn


def fixed_diff(entries):
    def diff_fn(session):
        return entries
    return diff_fn


@pytest.fixture
def ws(tmp_path):
    workspace = tmp_path / "workspace"
    upper = tmp_path / "upper"
    state_dir = tmp_path / "state"
    workspace.mkdir()
    upper.mkdir()
    state_dir.mkdir()
    return workspace, upper, state_dir


# --------------------------------------------------------------------------
# basic apply
# --------------------------------------------------------------------------

def test_commit_writes_new_file_to_workspace(ws):
    workspace, upper, state_dir = ws
    (upper / "a.txt").write_text("hello")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", "a.txt", "file", size_after=5, mode_after=0o100644)]
    commit_id = commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert (workspace / "a.txt").read_text() == "hello"
    assert commit_id


def test_commit_modifies_existing_file(ws):
    workspace, upper, state_dir = ws
    (workspace / "a.txt").write_text("old")
    (upper / "a.txt").write_text("new")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("modified", "a.txt", "file", size_before=3, size_after=3, mode_after=0o100644)]
    commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert (workspace / "a.txt").read_text() == "new"


def test_commit_deletes_file(ws):
    workspace, upper, state_dir = ws
    (workspace / "a.txt").write_text("gone")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("deleted", "a.txt", "file", size_before=4)]
    expected = diff_hash(entries, session, upper_resolve(upper))
    commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper), approved_hash=expected)
    assert not (workspace / "a.txt").exists()


def test_commit_creates_nested_directory_and_file(ws):
    workspace, upper, state_dir = ws
    (upper / "nested").mkdir(parents=True)
    (upper / "nested" / "b.txt").write_text("deep")
    session = open_session(workspace, upper, state_dir)
    entries = [
        DiffEntry("added", "nested", "dir", mode_after=0o40755),
        DiffEntry("added", "nested/b.txt", "file", size_after=4, mode_after=0o100644),
    ]
    commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert (workspace / "nested" / "b.txt").read_text() == "deep"


def test_commit_handles_symlink_add(ws):
    workspace, upper, state_dir = ws
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", "link", "symlink", symlink_target="a.txt")]
    commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert (workspace / "link").is_symlink()
    assert os.readlink(workspace / "link") == "a.txt"


def test_commit_deletes_directory_after_children(ws):
    workspace, upper, state_dir = ws
    (workspace / "d").mkdir()
    (workspace / "d" / "f.txt").write_text("x")
    session = open_session(workspace, upper, state_dir)
    entries = [
        DiffEntry("deleted", "d/f.txt", "file", size_before=1),
        DiffEntry("deleted", "d", "dir"),
    ]
    expected = diff_hash(entries, session, upper_resolve(upper))
    commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper), approved_hash=expected)
    assert not (workspace / "d").exists()


def test_commit_file_replaces_directory(ws):
    workspace, upper, state_dir = ws
    (workspace / "x").mkdir()
    (upper / "x").write_text("now a file")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("replaced_dir", "x", "file", size_after=10, mode_after=0o100644)]
    commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert (workspace / "x").is_file()
    assert (workspace / "x").read_text() == "now a file"


def test_commit_returns_empty_entries_without_error(ws):
    workspace, upper, state_dir = ws
    session = open_session(workspace, upper, state_dir)
    commit_id = commit(session, diff_fn=fixed_diff([]), resolve_fn=upper_resolve(upper))
    assert commit_id


# --------------------------------------------------------------------------
# policy gating
# --------------------------------------------------------------------------

def test_commit_rejects_protected_path(ws):
    workspace, upper, state_dir = ws
    session = make_session(workspace, upper, state_dir)
    entries = [DiffEntry("modified", ".env", "file", size_after=1, mode_after=0o100644)]
    with pytest.raises(PolicyRejected):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert not (workspace / ".env").exists()


def test_commit_requires_approval_for_pending_decision(ws):
    workspace, upper, state_dir = ws
    (workspace / "src").mkdir()
    (workspace / "src" / "main.c").write_text("x")
    session = make_session(workspace, upper, state_dir)
    entries = [DiffEntry("deleted", "src/main.c", "file", size_before=1)]
    with pytest.raises(ApprovalRequired) as excinfo:
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert excinfo.value.expected_hash
    assert (workspace / "src" / "main.c").exists()


def test_commit_succeeds_with_matching_approval_hash(ws):
    workspace, upper, state_dir = ws
    (workspace / "src").mkdir()
    (workspace / "src" / "main.c").write_text("x")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("deleted", "src/main.c", "file", size_before=1)]
    expected = diff_hash(entries, session, upper_resolve(upper))
    commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper), approved_hash=expected)
    assert not (workspace / "src" / "main.c").exists()


def test_commit_rejects_mismatched_approval_hash(ws):
    workspace, upper, state_dir = ws
    (workspace / "src").mkdir()
    (workspace / "src" / "main.c").write_text("x")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("deleted", "src/main.c", "file", size_before=1)]
    with pytest.raises(ApprovalMismatch):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper),
               approved_hash="deadbeef")
    assert (workspace / "src" / "main.c").exists()


def test_approval_hash_bound_to_content_not_just_metadata(ws):
    workspace, upper, state_dir = ws
    session = make_session(workspace, upper, state_dir)
    (upper / "a.txt").write_text("content-one")
    entries = [DiffEntry("added", "a.txt", "file", size_after=11, mode_after=0o100644)]
    h1 = diff_hash(entries, session, upper_resolve(upper))
    (upper / "a.txt").write_text("content-two")  # same size-ish shape? different content
    h2 = diff_hash(entries, session, upper_resolve(upper))
    assert h1 != h2


def test_approval_cannot_weaken_protected_defaults(ws):
    workspace, upper, state_dir = ws
    session = make_session(workspace, upper, state_dir)
    entries = [DiffEntry("modified", ".git/config", "file", size_after=1, mode_after=0o100644)]
    with pytest.raises(PolicyRejected):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper),
               approved_hash="anything-does-not-matter",
               policies=[Policy(protected=())])  # attempt to weaken; must still be rejected


def test_workspace_conflict_detected_from_snapshot(ws):
    workspace, upper, state_dir = ws
    (workspace / "a.txt").write_text("original")
    # Snapshot is captured and saved under the session's OWN directory at
    # session-creation time (mirrors the real layers.open_session flow),
    # not after an external mutation has already happened.
    session = open_session(workspace, upper, state_dir)
    # external process mutates the workspace after the session/snapshot was taken
    (workspace / "a.txt").write_text("externally changed")
    (upper / "a.txt").write_text("sandbox change")
    entries = [DiffEntry("modified", "a.txt", "file", size_before=8, size_after=13, mode_after=0o100644)]
    with pytest.raises(ApprovalRequired) as excinfo:
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert excinfo.value.decision.rule == "conflict"


def test_missing_snapshot_fails_closed_not_silently_skipped(ws):
    """No snapshot exists anywhere for this session (session-creation never
    ran capture_snapshot/save_snapshot). The old behavior silently treated
    this as "no conflicts possible"; the fixed behavior must fail closed:
    every touched path is conservatively treated as conflicting, which
    forces the same approval gate a real conflict would.
    """
    workspace, upper, state_dir = ws
    (workspace / "a.txt").write_text("unwatched")
    (upper / "a.txt").write_text("new")
    session = make_session(workspace, upper, state_dir)  # deliberately: no snapshot saved
    entries = [DiffEntry("modified", "a.txt", "file", size_before=9, size_after=3, mode_after=0o100644)]
    with pytest.raises(ApprovalRequired) as excinfo:
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert excinfo.value.decision.rule == "conflict"
    assert (workspace / "a.txt").read_text() == "unwatched"  # untouched; nothing applied


def test_explicit_empty_snapshot_injection_bypasses_fail_closed(ws):
    """An explicitly-injected snapshot (even an empty one) is a deliberate
    opt-out of fail-closed behavior, distinct from "caller forgot to save
    one" - tests (and any caller who already has prior state in hand) may
    still pass ``snapshot=`` directly.
    """
    workspace, upper, state_dir = ws
    session = make_session(workspace, upper, state_dir)
    (upper / "a.txt").write_text("hello")
    entries = [DiffEntry("added", "a.txt", "file", size_after=5, mode_after=0o100644)]
    commit_id = commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper), snapshot={})
    assert (workspace / "a.txt").read_text() == "hello"
    assert commit_id


def test_path_traversal_is_rejected(ws):
    workspace, upper, state_dir = ws
    session = make_session(workspace, upper, state_dir)
    entries = [DiffEntry("modified", "../escape.txt", "file", size_after=1, mode_after=0o100644)]
    with pytest.raises(CommitError):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))


def test_absolute_path_is_rejected(ws):
    workspace, upper, state_dir = ws
    session = make_session(workspace, upper, state_dir)
    entries = [DiffEntry("modified", "/etc/passwd", "file", size_after=1, mode_after=0o100644)]
    with pytest.raises(CommitError):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))


def test_symlink_ancestor_in_target_path_is_rejected(ws):
    workspace, upper, state_dir = ws
    real_dir = workspace / "real"
    real_dir.mkdir()
    (workspace / "linked").symlink_to(real_dir)
    (upper / "pwn.txt").write_text("x")
    session = make_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", "linked/pwn.txt", "file", size_after=1, mode_after=0o100644)]
    with pytest.raises(CommitError):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))


# --------------------------------------------------------------------------
# undo
# --------------------------------------------------------------------------

def test_undo_restores_deleted_file(ws):
    workspace, upper, state_dir = ws
    (workspace / "a.txt").write_text("precious")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("deleted", "a.txt", "file", size_before=8)]
    expected = diff_hash(entries, session, upper_resolve(upper))
    commit_id = commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper),
                        approved_hash=expected)
    assert not (workspace / "a.txt").exists()
    undo(workspace, state_dir, commit_id)
    assert (workspace / "a.txt").read_text() == "precious"


def test_undo_restores_overwritten_file(ws):
    workspace, upper, state_dir = ws
    (workspace / "a.txt").write_text("old")
    (upper / "a.txt").write_text("new")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("modified", "a.txt", "file", size_before=3, size_after=3, mode_after=0o100644)]
    commit_id = commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    undo(workspace, state_dir, commit_id)
    assert (workspace / "a.txt").read_text() == "old"


def test_undo_restores_removed_new_file_to_absent(ws):
    workspace, upper, state_dir = ws
    (upper / "a.txt").write_text("brand new")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", "a.txt", "file", size_after=9, mode_after=0o100644)]
    commit_id = commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert (workspace / "a.txt").exists()
    undo(workspace, state_dir, commit_id)
    assert not (workspace / "a.txt").exists()


def test_undo_unknown_commit_id_raises(ws):
    workspace, upper, state_dir = ws
    with pytest.raises(commitmod.UnknownCommit):
        undo(workspace, state_dir, "nope-does-not-exist")


# --------------------------------------------------------------------------
# crash + recovery (subprocess kill -9, only the committer process)
# --------------------------------------------------------------------------

_CRASH_SCRIPT = textwrap.dedent("""
    import sys
    sys.path.insert(0, {repo_src!r})
    from pathlib import Path
    from lilguy.policy.commit import commit, capture_snapshot, save_snapshot
    from lilguy.sandbox.backend import Session, SessionConfig, DiffEntry

    workspace = Path({workspace!r})
    upper = Path({upper!r})
    state_dir = Path({state_dir!r})
    kill_index = {kill_index!r}

    def diff_fn(session):
        return [
            DiffEntry("modified", "a.txt", "file", size_before=3, size_after=3, mode_after=0o100644),
            DiffEntry("added", "b.txt", "file", size_after=3, mode_after=0o100644),
        ]

    def resolve_fn(session, rel):
        p = upper / rel
        return p if p.exists() else None

    def crash_hook(index, entry):
        if index == kill_index:
            import os, signal
            os.kill(os.getpid(), signal.SIGKILL)

    session = Session(workspace=workspace, directory=upper, cfg=SessionConfig(state_dir=state_dir))
    # Mirror the real flow: the session's own directory holds its snapshot,
    # captured and saved at session-creation time ("crash child explicit
    # save" - this script IS the child process that will be killed, so it
    # must do this itself before calling commit()).
    save_snapshot(session.directory, capture_snapshot(workspace))
    commit(session, diff_fn=diff_fn, resolve_fn=resolve_fn, crash_hook=crash_hook)
""")


def _run_crash_commit(repo_src, workspace, upper, state_dir, kill_index):
    script = _CRASH_SCRIPT.format(
        repo_src=str(repo_src), workspace=str(workspace), upper=str(upper),
        state_dir=str(state_dir), kill_index=kill_index,
    )
    proc = subprocess.run([sys.executable, "-c", script])
    return proc.returncode


@pytest.mark.parametrize("kill_index", [0, 1])
def test_crash_during_commit_then_recover_restores_prestate(ws, kill_index):
    workspace, upper, state_dir = ws
    (workspace / "a.txt").write_text("old")
    (upper / "a.txt").write_text("new")
    (upper / "b.txt").write_text("fresh")
    before = {"a.txt": (workspace / "a.txt").read_bytes()}

    repo_src = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    returncode = _run_crash_commit(repo_src, workspace, upper, state_dir, kill_index)
    assert returncode != 0  # killed by SIGKILL

    recovered = recover(workspace, state_dir)
    assert len(recovered) == 1

    assert (workspace / "a.txt").read_bytes() == before["a.txt"]
    assert not (workspace / "b.txt").exists()

    # recover is idempotent: nothing left to recover, and workspace state unchanged
    assert recover(workspace, state_dir) == []
    assert (workspace / "a.txt").read_bytes() == before["a.txt"]
    assert not (workspace / "b.txt").exists()


def test_successful_commit_leaves_no_journal_but_a_committed_record(ws):
    workspace, upper, state_dir = ws
    (upper / "a.txt").write_text("x")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", "a.txt", "file", size_after=1, mode_after=0o100644)]
    commit_id = commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert not list((state_dir / "journal").glob("*.json"))
    assert (state_dir / "committed" / f"{commit_id}.json").exists()


def test_capture_and_load_snapshot_roundtrip(ws):
    workspace, upper, state_dir = ws
    (workspace / "a.txt").write_text("x")
    snap = capture_snapshot(workspace)
    save_snapshot(state_dir, snap)
    loaded = load_snapshot(state_dir)
    assert loaded == snap
    assert "a.txt" in loaded


# --------------------------------------------------------------------------
# destructive type replacement: deletion ordering + full subtree preimage
# --------------------------------------------------------------------------

def test_replace_nonempty_dir_with_file_while_deleting_child_rolls_back_fully(ws):
    """d is a non-empty directory; the diff replaces d with a plain file
    AND separately deletes d/child. The only safe order is to delete the
    child while d is still a directory, then replace d with the file - and
    if the commit is undone, every original descendant (not just the dir
    entry itself) must come back, because the type-replacement destroyed
    the whole subtree in one step.
    """
    workspace, upper, state_dir = ws
    d = workspace / "d"
    d.mkdir()
    (d / "child").write_text("irreplaceable")
    (d / "keep").write_text("also precious")
    (upper / "d").write_text("now a file")
    session = open_session(workspace, upper, state_dir)
    entries = [
        DiffEntry("deleted", "d/child", "file", size_before=13),
        DiffEntry("replaced_dir", "d", "file", size_after=10, mode_after=0o100644),
    ]
    expected = diff_hash(entries, session, upper_resolve(upper))
    commit_id = commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper),
                        approved_hash=expected)
    assert (workspace / "d").is_file()
    assert (workspace / "d").read_text() == "now a file"

    undo(workspace, state_dir, commit_id)
    assert (workspace / "d").is_dir()
    assert (workspace / "d" / "child").read_text() == "irreplaceable"
    assert (workspace / "d" / "keep").read_text() == "also precious"


def test_replace_nonempty_dir_with_file_crash_mid_commit_recovers_subtree(ws):
    """Same destructive replacement, but the process is journaled and we
    simulate a crash mid-commit via recover(): every original descendant of
    the replaced directory must be restored, not just the top-level path.
    """
    workspace, upper, state_dir = ws
    d = workspace / "d"
    d.mkdir()
    (d / "child").write_text("irreplaceable")
    (upper / "d").write_text("now a file")
    session = open_session(workspace, upper, state_dir)
    entries = [
        DiffEntry("deleted", "d/child", "file", size_before=13),
        DiffEntry("replaced_dir", "d", "file", size_after=10, mode_after=0o100644),
    ]
    expected = diff_hash(entries, session, upper_resolve(upper))

    def crash_hook(index, entry):
        if entry.path == "d":  # kill right before the destructive replace
            raise commitmod.CommitError("simulated crash before journal update")

    with pytest.raises(commitmod.CommitError):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper),
               approved_hash=expected, crash_hook=crash_hook)

    assert (workspace / "d").is_dir()
    assert (workspace / "d" / "child").read_text() == "irreplaceable"


# --------------------------------------------------------------------------
# special files: no safe recoverable representation yet
# --------------------------------------------------------------------------

def test_commit_rejects_touching_existing_special_file(ws):
    workspace, upper, state_dir = ws
    fifo_path = workspace / "myfifo"
    os.mkfifo(fifo_path)
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("deleted", "myfifo", "special")]
    with pytest.raises(CommitError):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    assert statmod_is_fifo(fifo_path)


def statmod_is_fifo(path):
    import stat
    return stat.S_ISFIFO(path.lstat().st_mode)


# --------------------------------------------------------------------------
# missing/non-regular source content must fail, not silently write empty
# --------------------------------------------------------------------------

def test_commit_rejects_missing_source_instead_of_writing_empty(ws):
    workspace, upper, state_dir = ws
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", "ghost.txt", "file", size_after=5, mode_after=0o100644)]

    def vanished_resolve(session, rel):
        return upper / rel  # never actually created on disk

    with pytest.raises(CommitError):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=vanished_resolve)
    assert not (workspace / "ghost.txt").exists()


def test_commit_rejects_nonregular_source(ws):
    workspace, upper, state_dir = ws
    (upper / "srcdir").mkdir()  # a directory, not a regular file
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", "a.txt", "file", size_after=1, mode_after=0o100644)]

    def dir_resolve(session, rel):
        return upper / "srcdir"

    with pytest.raises(CommitError):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=dir_resolve)
    assert not (workspace / "a.txt").exists()


# --------------------------------------------------------------------------
# journal/lock location must not overlap the workspace
# --------------------------------------------------------------------------

def test_state_dir_overlapping_workspace_is_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    upper = tmp_path / "upper"
    upper.mkdir()
    state_dir = workspace / ".state"  # INSIDE the workspace - must be rejected
    session = make_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", "a.txt", "file", size_after=1, mode_after=0o100644)]
    with pytest.raises(CommitError):
        commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))


# --------------------------------------------------------------------------
# undo() must not allow arbitrary commit_id path traversal
# --------------------------------------------------------------------------

def test_undo_rejects_path_traversal_commit_id(ws):
    workspace, upper, state_dir = ws
    with pytest.raises(commitmod.UnknownCommit):
        undo(workspace, state_dir, "../../etc/passwd")
_CRASH_AFTER_APPLY_SCRIPT = textwrap.dedent("""
    import sys
    sys.path.insert(0, {repo_src!r})
    from pathlib import Path
    from lilguy.policy import commit as commitmod
    from lilguy.sandbox.backend import Session, SessionConfig, DiffEntry

    workspace = Path({workspace!r})
    upper = Path({upper!r})
    state_dir = Path({state_dir!r})
    kill_index = {kill_index!r}

    def diff_fn(session):
        return [
            DiffEntry("modified", "a.txt", "file", size_before=3, size_after=3, mode_after=0o100644),
            DiffEntry("added", "b.txt", "file", size_after=3, mode_after=0o100644),
        ]

    def resolve_fn(session, rel):
        p = upper / rel
        return p if p.exists() else None

    # Kill the process from INSIDE _apply_one, AFTER the original mutation
    # has already completed on disk, but BEFORE commit()'s loop gets a
    # chance to persist anything past that point. This is exactly the gap
    # fixed by writing the durable "about to touch index N" journal record
    # BEFORE the mutation instead of after it.
    _orig_apply_one = commitmod._apply_one
    def _killing_apply_one(workspace_, entry, resolve_fn_, session_):
        _orig_apply_one(workspace_, entry, resolve_fn_, session_)
        ordered_index = {{"a.txt": 0, "b.txt": 1}}[entry.path]
        if ordered_index == kill_index:
            import os, signal
            os.kill(os.getpid(), signal.SIGKILL)
    commitmod._apply_one = _killing_apply_one

    session = Session(workspace=workspace, directory=upper, cfg=SessionConfig(state_dir=state_dir))
    commitmod.save_snapshot(session.directory, commitmod.capture_snapshot(workspace))
    commitmod.commit(session, diff_fn=diff_fn, resolve_fn=resolve_fn)
""")


def _run_crash_after_apply_commit(repo_src, workspace, upper, state_dir, kill_index):
    script = _CRASH_AFTER_APPLY_SCRIPT.format(
        repo_src=str(repo_src), workspace=str(workspace), upper=str(upper),
        state_dir=str(state_dir), kill_index=kill_index,
    )
    proc = subprocess.run([sys.executable, "-c", script])
    return proc.returncode


@pytest.mark.parametrize("kill_index", [0, 1])
def test_crash_after_apply_returns_before_journal_update_still_recovers(ws, kill_index):
    """Regression for the exact gap: SIGKILL fired from inside _apply_one
    AFTER the real mutation has landed on disk but before anything else in
    commit()'s loop runs. Before the fix, applied_index was only persisted
    AFTER _apply_one returned, so this exact kill point left an untracked,
    unrecoverable mutation. After the fix, the durable intent record for
    this index is written BEFORE _apply_one is even called, so recovery
    still knows to roll it back.
    """
    workspace, upper, state_dir = ws
    (workspace / "a.txt").write_text("old")
    (upper / "a.txt").write_text("new")
    (upper / "b.txt").write_text("fresh")
    before = (workspace / "a.txt").read_bytes()

    repo_src = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    returncode = _run_crash_after_apply_commit(repo_src, workspace, upper, state_dir, kill_index)
    assert returncode != 0  # killed by SIGKILL
    recovered = recover(workspace, state_dir)
    assert len(recovered) == 1

    # The mutation that happened right before the kill must have been
    # rolled back along with everything else - nothing left dangling.
    assert (workspace / "a.txt").read_bytes() == before
    assert not (workspace / "b.txt").exists()
