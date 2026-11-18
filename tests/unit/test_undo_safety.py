"""Undo must never destroy work the human did after the commit, and old undo data expires."""
import json
import os
import time

import pytest

from lilguy.policy import commit as commitmod
from lilguy.policy.commit import commit, undo
from lilguy.sandbox.backend import DiffEntry
from tests.unit.test_commit import fixed_diff, open_session, upper_resolve, ws  # noqa: F401


def _commit_new_file(workspace, upper, state_dir, name="a.txt", text="new"):
    (upper / name).write_text(text)
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", name, "file", size_after=len(text), mode_after=0o100644)]
    return commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))


def test_undo_refuses_after_the_committed_file_was_edited(ws):  # noqa: F811
    workspace, upper, state_dir = ws
    commit_id = _commit_new_file(workspace, upper, state_dir)
    (workspace / "a.txt").write_text("my later edit")
    with pytest.raises(commitmod.UndoConflict) as err:
        undo(workspace, state_dir, commit_id)
    assert "a.txt" in str(err.value)
    assert (workspace / "a.txt").read_text() == "my later edit"


def test_undo_refuses_when_a_file_was_added_inside_a_committed_dir(ws):  # noqa: F811
    workspace, upper, state_dir = ws
    (upper / "pkg").mkdir()
    (upper / "pkg" / "x.py").write_text("x")
    session = open_session(workspace, upper, state_dir)
    entries = [DiffEntry("added", "pkg", "dir", mode_after=0o40755),
               DiffEntry("added", "pkg/x.py", "file", size_after=1, mode_after=0o100644)]
    commit_id = commit(session, diff_fn=fixed_diff(entries), resolve_fn=upper_resolve(upper))
    (workspace / "pkg" / "mine.py").write_text("hand written")
    with pytest.raises(commitmod.UndoConflict):
        undo(workspace, state_dir, commit_id)
    assert (workspace / "pkg" / "mine.py").read_text() == "hand written"


def test_undo_refuses_after_a_mode_change(ws):  # noqa: F811
    workspace, upper, state_dir = ws
    commit_id = _commit_new_file(workspace, upper, state_dir)
    os.chmod(workspace / "a.txt", 0o600)
    with pytest.raises(commitmod.UndoConflict):
        undo(workspace, state_dir, commit_id)


def test_undo_still_works_when_nothing_changed_since(ws):  # noqa: F811
    workspace, upper, state_dir = ws
    commit_id = _commit_new_file(workspace, upper, state_dir)
    undo(workspace, state_dir, commit_id)
    assert not (workspace / "a.txt").exists()
    with pytest.raises(commitmod.UnknownCommit):
        undo(workspace, state_dir, commit_id)


def test_list_commits_newest_first(ws):  # noqa: F811
    workspace, upper, state_dir = ws
    first = _commit_new_file(workspace, upper, state_dir, "a.txt")
    time.sleep(0.002)
    second = _commit_new_file(workspace, upper, state_dir, "b.txt")
    listed = commitmod.list_commits(state_dir)
    assert [c["commit_id"] for c in listed][:2] == [second, first]
    assert listed[0]["paths"] == ["b.txt"]


def test_prune_drops_undo_data_older_than_retention(ws):  # noqa: F811
    workspace, upper, state_dir = ws
    old = _commit_new_file(workspace, upper, state_dir, "a.txt")
    fresh = _commit_new_file(workspace, upper, state_dir, "b.txt")
    old_path = state_dir / "committed" / f"{old}.json"
    record = json.loads(old_path.read_text())
    record["committed_at"] = time.time() - 8 * 86400
    old_path.write_text(json.dumps(record))
    assert commitmod.prune_commits(state_dir, retention_s=7 * 86400) == [old]
    assert [c["commit_id"] for c in commitmod.list_commits(state_dir)] == [fresh]
