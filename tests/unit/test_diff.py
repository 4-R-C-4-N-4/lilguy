"""Unit tests for lilguy.sandbox.diff (step/session diff against overlay layers)."""
from __future__ import annotations

import os

import pytest

from lilguy.sandbox import diff, layers
from lilguy.sandbox.backend import SessionConfig


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("hello")
    (ws / "big.txt").write_text("x" * 100)
    (ws / "sub").mkdir()
    (ws / "sub" / "b.txt").write_text("world")
    (ws / "sub" / "c.txt").write_text("keep-me")
    return ws


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "state"


def mk_session(workspace, state_dir, **kw):
    return layers.open_session(workspace, SessionConfig(state_dir=state_dir, **kw))


def by_path(entries, path):
    for e in entries:
        if e.path == path:
            return e
    raise KeyError(path)


# ---- step_diff: added ----

def test_step_diff_added_file(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "new.txt").write_text("fresh content")
    entries = diff.step_diff(s, u0)
    e = by_path(entries, "new.txt")
    assert e.op == "added"
    assert e.kind == "file"
    assert e.size_after == len("fresh content")
    assert e.size_before is None


def test_step_diff_added_dir_recurses(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "newdir").mkdir()
    (u0 / "newdir" / "inner.txt").write_text("hi")
    entries = diff.step_diff(s, u0)
    assert by_path(entries, "newdir").op == "added"
    assert by_path(entries, "newdir").kind == "dir"
    assert by_path(entries, "newdir/inner.txt").op == "added"


# ---- step_diff: modified / meta ----

def test_step_diff_modified_file_different_content_same_size(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "a.txt").write_text("HELLO")  # same length as "hello", different content
    entries = diff.step_diff(s, u0)
    e = by_path(entries, "a.txt")
    assert e.op == "modified"
    assert e.size_before == 5
    assert e.size_after == 5


def test_step_diff_modified_file_different_size(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "a.txt").write_text("hello world, much longer now")
    entries = diff.step_diff(s, u0)
    e = by_path(entries, "a.txt")
    assert e.op == "modified"


def test_step_diff_meta_same_content_mode_change(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "a.txt").write_text("hello")  # byte-identical to lower
    os.chmod(u0 / "a.txt", 0o600)
    entries = diff.step_diff(s, u0)
    e = by_path(entries, "a.txt")
    assert e.op == "meta"
    assert e.mode_before is not None and e.mode_after is not None
    assert e.mode_before != e.mode_after


def test_step_diff_no_entry_for_truly_unchanged_file(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "a.txt").write_text("hello")
    os.chmod(u0 / "a.txt", os.lstat(workspace / "a.txt").st_mode)
    entries = diff.step_diff(s, u0)
    assert all(e.path != "a.txt" for e in entries)


# ---- step_diff: deleted (mocked whiteout) ----

def test_step_diff_deleted_file(workspace, state_dir, monkeypatch):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    placeholder = u0 / "a.txt"
    placeholder.write_text("tombstone")
    monkeypatch.setattr(diff, "is_whiteout", lambda p: p == placeholder)
    entries = diff.step_diff(s, u0)
    e = by_path(entries, "a.txt")
    assert e.op == "deleted"
    assert e.kind == "file"
    assert e.size_before == len("hello")


def test_step_diff_deleted_dir_recurses_descendants(workspace, state_dir, monkeypatch):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    placeholder = u0 / "sub"
    placeholder.write_text("tombstone")
    monkeypatch.setattr(diff, "is_whiteout", lambda p: p == placeholder)
    entries = diff.step_diff(s, u0)
    paths = {e.path for e in entries}
    assert "sub" in paths
    assert "sub/b.txt" in paths
    assert "sub/c.txt" in paths
    assert all(e.op == "deleted" for e in entries if e.path.startswith("sub"))


# ---- step_diff: opaque dir ----

def test_step_diff_opaque_dir_is_replaced_dir_with_deletes(workspace, state_dir, monkeypatch):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "sub").mkdir()
    (u0 / "sub" / "b.txt").write_text("world")  # re-added, unchanged content
    monkeypatch.setattr(diff, "is_opaque", lambda p: p == u0 / "sub")
    entries = diff.step_diff(s, u0)
    replaced = by_path(entries, "sub")
    assert replaced.op == "replaced_dir"
    assert replaced.kind == "dir"
    # c.txt was not re-added under the opaque dir -> deleted
    deleted_c = by_path(entries, "sub/c.txt")
    assert deleted_c.op == "deleted"
    # b.txt re-added with identical content -> meta, not reported as deleted
    assert all(e.path != "sub/b.txt" or e.op != "deleted" for e in entries)


def test_step_diff_opaque_dir_without_lower_is_added(workspace, state_dir, monkeypatch):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "brandnew").mkdir()
    (u0 / "brandnew" / "x.txt").write_text("x")
    monkeypatch.setattr(diff, "is_opaque", lambda p: p == u0 / "brandnew")
    entries = diff.step_diff(s, u0)
    assert by_path(entries, "brandnew").op == "added"


# ---- step_diff: mode / symlink / binary / special ----

def test_step_diff_symlink_added(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "link.txt").symlink_to("a.txt")
    entries = diff.step_diff(s, u0)
    e = by_path(entries, "link.txt")
    assert e.op == "added"
    assert e.kind == "symlink"
    assert e.symlink_target == "a.txt"


def test_step_diff_symlink_target_changed(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "link.txt").symlink_to("a.txt")
    layers.rollback_step(s)
    u0 = layers.new_layer(s)
    # Build scenario across two layers: layer0 adds link -> target a; layer1 changes target -> target big
    u1 = layers.new_layer(s)
    (s.uppers[0] / "link.txt").symlink_to("a.txt")
    (u1 / "link.txt").symlink_to("big.txt")
    entries = diff.step_diff(s, u1)
    e = by_path(entries, "link.txt")
    assert e.op == "modified"
    assert e.symlink_target == "big.txt"


def test_step_diff_binary_detection(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "bin.dat").write_bytes(b"\x00\x01\x02binary")
    entries = diff.step_diff(s, u0)
    e = by_path(entries, "bin.dat")
    assert e.is_binary is True


def test_step_diff_text_not_binary(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "text.txt").write_text("just text")
    entries = diff.step_diff(s, u0)
    assert by_path(entries, "text.txt").is_binary is False


# ---- step_diff: large file hashing only when size equal ----

def test_step_diff_large_file_size_change_skips_hash(workspace, state_dir, monkeypatch):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "big.txt").write_text("y" * 50)  # different size from lower (100 'x's)
    called = {"n": 0}
    orig = diff._hash_file

    def spy(path):
        called["n"] += 1
        return orig(path)

    monkeypatch.setattr(diff, "_hash_file", spy)
    entries = diff.step_diff(s, u0)
    assert by_path(entries, "big.txt").op == "modified"
    assert called["n"] == 0


# ---- session_diff: folding ----

def test_session_diff_add_then_delete_cancels(workspace, state_dir, monkeypatch):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "temp.txt").write_text("short-lived")
    u1 = layers.new_layer(s)
    placeholder = u1 / "temp.txt"
    placeholder.write_text("tombstone")
    monkeypatch.setattr(diff, "is_whiteout", lambda p: p == placeholder)
    entries = diff.session_diff(s)
    assert all(e.path != "temp.txt" for e in entries)


def test_session_diff_delete_then_readd_is_modified(workspace, state_dir, monkeypatch):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    placeholder = u0 / "a.txt"
    placeholder.write_text("tombstone")
    monkeypatch.setattr(diff, "is_whiteout", lambda p: p == placeholder)
    u1 = layers.new_layer(s)
    (u1 / "a.txt").write_text("brand new content")
    entries = diff.session_diff(s)
    e = by_path(entries, "a.txt")
    assert e.op == "modified"


def test_session_diff_multiple_modifications_collapse_to_one_modified(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "a.txt").write_text("v1-longer")
    u1 = layers.new_layer(s)
    (u1 / "a.txt").write_text("v2-final")
    entries = diff.session_diff(s)
    matches = [e for e in entries if e.path == "a.txt"]
    assert len(matches) == 1
    assert matches[0].op == "modified"
    assert matches[0].size_before == len("hello")


def test_session_diff_unrelated_adds_across_layers(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    u0 = layers.new_layer(s)
    (u0 / "one.txt").write_text("1")
    u1 = layers.new_layer(s)
    (u1 / "two.txt").write_text("2")
    entries = diff.session_diff(s)
    assert by_path(entries, "one.txt").op == "added"
    assert by_path(entries, "two.txt").op == "added"


def test_session_diff_empty_session_is_empty(workspace, state_dir):
    s = mk_session(workspace, state_dir)
    layers.new_layer(s)
    entries = diff.session_diff(s)
    assert entries == []
