"""Unit tests for lilguy.sandbox.layers (host-side layer stack + resolver)."""
from __future__ import annotations

import stat

import pytest

from lilguy.sandbox import diff, layers
from lilguy.sandbox.backend import SessionConfig


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("hello")
    (ws / "sub").mkdir()
    (ws / "sub" / "b.txt").write_text("world")
    return ws


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    return d


def cfg(state_dir, **kw):
    return SessionConfig(state_dir=state_dir, **kw)


# ---- open_session ----

def test_open_session_creates_private_state_outside_workspace(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    assert s.workspace == workspace.resolve()
    assert s.directory.is_dir()
    assert not str(s.directory).startswith(str(workspace.resolve()))
    assert s.uppers == []
    assert s.cwd == "."
    assert s.closed is False
    mode = stat.S_IMODE(s.directory.stat().st_mode)
    assert mode == 0o700


def test_open_session_rejects_state_dir_inside_workspace(workspace):
    bad_cfg = cfg(workspace / "state")
    with pytest.raises(layers.LayerError):
        layers.open_session(workspace, bad_cfg)


def test_open_session_rejects_workspace_inside_state_dir(tmp_path):
    state = tmp_path / "state"
    ws = state / "nested" / "ws"
    ws.mkdir(parents=True)
    with pytest.raises(layers.LayerError):
        layers.open_session(ws, cfg(state))


def test_open_session_default_state_dir_uses_xdg(workspace, tmp_path, monkeypatch):
    xdg = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg))
    s = layers.open_session(workspace, SessionConfig())
    assert str(s.directory).startswith(str(xdg / "lilguy" / "sessions"))
    layers.discard(s)


# ---- new_layer ----

def test_new_layer_appends_upper_oldest_first(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    u0 = layers.new_layer(s)
    u1 = layers.new_layer(s)
    assert s.uppers == [u0, u1]
    assert u0.is_dir() and u1.is_dir()
    assert u0 != u1
    mode = stat.S_IMODE(u0.stat().st_mode)
    assert mode == 0o700


def test_new_layer_fails_closed_at_max_layers(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir, max_layers=2))
    layers.new_layer(s)
    layers.new_layer(s)
    with pytest.raises(layers.LayerError):
        layers.new_layer(s)


def test_new_layer_rejects_on_closed_session(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    layers.discard(s)
    with pytest.raises(layers.LayerError):
        layers.new_layer(s)


# ---- resolve ----

def test_resolve_falls_back_to_workspace(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    layers.new_layer(s)
    found = layers.resolve(s, "a.txt")
    assert found == workspace / "a.txt"


def test_resolve_prefers_newest_upper(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    u0 = layers.new_layer(s)
    u1 = layers.new_layer(s)
    (u0 / "a.txt").write_text("v0")
    (u1 / "a.txt").write_text("v1")
    found = layers.resolve(s, "a.txt")
    assert found == u1 / "a.txt"


def test_resolve_none_for_whiteout_leaf(workspace, state_dir, monkeypatch):
    s = layers.open_session(workspace, cfg(state_dir))
    u0 = layers.new_layer(s)
    (u0 / "a.txt").write_text("tombstone-placeholder")
    monkeypatch.setattr(diff, "is_whiteout", lambda p: p == u0 / "a.txt")
    assert layers.resolve(s, "a.txt") is None


def test_resolve_none_for_ancestor_whiteout(workspace, state_dir, monkeypatch):
    s = layers.open_session(workspace, cfg(state_dir))
    u0 = layers.new_layer(s)
    (u0 / "sub").write_text("tombstone-placeholder")
    monkeypatch.setattr(diff, "is_whiteout", lambda p: p == u0 / "sub")
    assert layers.resolve(s, "sub/b.txt") is None


def test_resolve_none_for_ancestor_opaque_dir_hiding_lower(workspace, state_dir, monkeypatch):
    s = layers.open_session(workspace, cfg(state_dir))
    u0 = layers.new_layer(s)
    (u0 / "sub").mkdir()
    monkeypatch.setattr(diff, "is_opaque", lambda p: p == u0 / "sub")
    # b.txt only exists in the workspace lower, hidden by the opaque upper dir
    assert layers.resolve(s, "sub/b.txt") is None


def test_resolve_finds_file_added_under_opaque_dir(workspace, state_dir, monkeypatch):
    s = layers.open_session(workspace, cfg(state_dir))
    u0 = layers.new_layer(s)
    (u0 / "sub").mkdir()
    (u0 / "sub" / "new.txt").write_text("fresh")
    monkeypatch.setattr(diff, "is_opaque", lambda p: p == u0 / "sub")
    assert layers.resolve(s, "sub/new.txt") == u0 / "sub" / "new.txt"


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside", "sub/../../outside", "a/../../b"])
def test_resolve_rejects_absolute_and_dotdot(workspace, state_dir, bad):
    s = layers.open_session(workspace, cfg(state_dir))
    layers.new_layer(s)
    with pytest.raises(layers.LayerError):
        layers.resolve(s, bad)


def test_resolve_does_not_follow_leaf_symlink_target_but_returns_path(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    u0 = layers.new_layer(s)
    target = workspace / "a.txt"
    link = u0 / "link.txt"
    link.symlink_to(target)
    found = layers.resolve(s, "link.txt")
    assert found == link
    assert found.is_symlink()


def test_resolve_on_closed_session_raises(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    layers.discard(s)
    with pytest.raises(layers.LayerError):
        layers.resolve(s, "a.txt")


def test_resolve_with_explicit_uppers_override(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    u0 = layers.new_layer(s)
    u1 = layers.new_layer(s)
    (u0 / "a.txt").write_text("v0")
    (u1 / "a.txt").write_text("v1")
    # explicit subset: only u0 should be consulted
    found = layers.resolve(s, "a.txt", uppers=[u0])
    assert found == u0 / "a.txt"


# ---- rollback_step / discard ----

def test_rollback_step_drops_top_layer(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    u0 = layers.new_layer(s)
    u1 = layers.new_layer(s)
    layers.rollback_step(s)
    assert s.uppers == [u0]
    assert not u1.exists()
    assert u0.exists()


def test_rollback_step_on_empty_session_raises(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    with pytest.raises(layers.LayerError):
        layers.rollback_step(s)


def test_discard_removes_private_state_and_closes(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    layers.new_layer(s)
    directory = s.directory
    layers.discard(s)
    assert s.closed is True
    assert not directory.exists()
    assert not workspace.exists() or list(workspace.iterdir())  # host workspace untouched


def test_discard_never_touches_workspace_contents(workspace, state_dir):
    before = sorted(p.name for p in workspace.rglob("*"))
    s = layers.open_session(workspace, cfg(state_dir))
    layers.new_layer(s)
    layers.discard(s)
    after = sorted(p.name for p in workspace.rglob("*"))
    assert before == after


def test_discard_is_idempotent(workspace, state_dir):
    s = layers.open_session(workspace, cfg(state_dir))
    layers.discard(s)
    layers.discard(s)  # must not raise
    assert s.closed is True
