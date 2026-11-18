from lilguy.sandbox import diff, layers
from lilguy.sandbox.backend import SessionConfig


def make_session(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return layers.open_session(workspace, SessionConfig(state_dir=tmp_path / "state"))


def test_symlink_replacing_directory_hides_all_lower_descendants(tmp_path):
    s = make_session(tmp_path)
    (s.workspace / "d").mkdir()
    (s.workspace / "d" / "file").write_text("old")
    upper = layers.new_layer(s)
    (upper / "d").symlink_to("elsewhere")
    assert layers.resolve(s, "d/file") is None


def test_reverting_modified_file_to_original_cancels_net_diff(tmp_path):
    s = make_session(tmp_path)
    (s.workspace / "a").write_text("old")
    (layers.new_layer(s) / "a").write_text("new")
    (layers.new_layer(s) / "a").write_text("old")
    assert diff.session_diff(s) == []


def test_directory_chmod_is_a_visible_effect(tmp_path):
    s = make_session(tmp_path)
    (s.workspace / "d").mkdir(mode=0o755)
    upper = layers.new_layer(s)
    (upper / "d").mkdir(mode=0o700)
    entries = diff.step_diff(s, upper)
    assert any(e.path == "d" and e.op == "meta" and e.mode_after == 0o700 for e in entries)


def test_state_symlink_into_workspace_is_rejected(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "state-link").symlink_to(ws, target_is_directory=True)
    import pytest
    with pytest.raises(layers.LayerError):
        layers.open_session(ws, SessionConfig(state_dir=tmp_path / "state-link"))


def test_nested_new_files_are_not_dropped_by_recursive_walk(tmp_path):
    s = make_session(tmp_path)
    upper = layers.new_layer(s)
    (upper / "a" / "b" / "c").mkdir(parents=True)
    (upper / "a" / "b" / "c" / "file").write_text("new")
    entries = diff.session_diff(s)
    assert any(e.path == "a/b/c/file" and e.op == "added" for e in entries)


def test_deleted_tree_does_not_count_descendants_hidden_by_opaque_lower(tmp_path, monkeypatch):
    s = make_session(tmp_path)
    (s.workspace / "d").mkdir()
    (s.workspace / "d" / "old").write_text("old")
    first = layers.new_layer(s)
    (first / "d").mkdir()
    (first / "d" / "new").write_text("new")
    last = layers.new_layer(s)
    (last / "d").write_text("whiteout marker")
    monkeypatch.setattr(diff, "is_opaque", lambda p: p == first / "d")
    monkeypatch.setattr(diff, "is_whiteout", lambda p: p == last / "d")
    assert {e.path for e in diff.step_diff(s, last)} == {"d", "d/new"}


def test_merged_listing_never_follows_an_upper_directory_symlink(tmp_path):
    s = make_session(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private").write_text("must not be listed")
    upper = layers.new_layer(s)
    (upper / "d").symlink_to(outside, target_is_directory=True)
    assert diff._merged_listing("d", [upper], s.workspace) == {}


def test_rollback_removes_unreadable_private_directories_and_can_continue(tmp_path):
    s = make_session(tmp_path)
    upper = layers.new_layer(s)
    (upper / "locked").mkdir()
    (upper / "locked" / "file").write_text("private")
    (upper / "locked").chmod(0)
    layers.rollback_step(s)
    assert not upper.parent.exists()
    assert layers.new_layer(s).is_dir()


def test_opaque_ancestor_deletes_hidden_nested_descendants(tmp_path, monkeypatch):
    s = make_session(tmp_path)
    (s.workspace / "d" / "sub").mkdir(parents=True)
    (s.workspace / "d" / "sub" / "old").write_text("old")
    upper = layers.new_layer(s)
    (upper / "d" / "sub").mkdir(parents=True)
    (upper / "d" / "sub" / "new").write_text("new")
    monkeypatch.setattr(diff, "is_opaque", lambda p: p == upper / "d")
    entries = diff.session_diff(s)
    assert any(e.path == "d/sub/old" and e.op == "deleted" for e in entries)
    assert any(e.path == "d/sub/new" and e.op == "added" for e in entries)


def test_snapshot_is_session_local_and_automatic(tmp_path):
    s = make_session(tmp_path)
    assert (s.directory / "commit_snapshot.json").is_file()
