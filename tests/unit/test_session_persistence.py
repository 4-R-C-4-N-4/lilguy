"""A kept session must be reloadable by a separate trusted process (approve/deny/continue)."""
import json
import os

import pytest

from lilguy.sandbox import layers, persist
from lilguy.sandbox.backend import SessionConfig


def _open(tmp_path, **cfg):
    ws = tmp_path / "ws"
    ws.mkdir()
    return layers.open_session(ws, SessionConfig(state_dir=tmp_path / "state", **cfg))


def test_reload_reproduces_config_layers_and_cwd(tmp_path):
    s = _open(tmp_path, timeout_s=1234, stall_timeout_s=7, max_processes=9)
    layers.new_layer(s)
    s.cwd = "sub"
    persist.record_step(s)
    layers.new_layer(s)
    s.cwd = "sub/deeper"
    persist.record_step(s)
    again = persist.load_session(s.directory)
    assert again.workspace == s.workspace
    assert again.uppers == s.uppers
    assert again.cwd == "sub/deeper"
    assert again.cfg.timeout_s == 1234 and again.cfg.stall_timeout_s == 7 and again.cfg.max_processes == 9
    assert again.cfg.protected == s.cfg.protected


def test_reload_cwd_follows_rollback(tmp_path):
    s = _open(tmp_path)
    for cwd in ("a", "b"):
        layers.new_layer(s)
        s.cwd = cwd
        persist.record_step(s)
    layers.rollback_step(s)
    persist.record_step(s)
    assert persist.load_session(s.directory).cwd == "a"


def test_generation_changes_on_every_record(tmp_path):
    s = _open(tmp_path)
    first = persist.generation(s.directory)
    layers.new_layer(s)
    persist.record_step(s)
    assert persist.generation(s.directory) == first + 1


@pytest.mark.parametrize("tamper", ["symlink", "mode", "cwd", "gap", "workspace"])
def test_reload_refuses_tampered_or_unsafe_state(tmp_path, tamper):
    s = _open(tmp_path)
    layers.new_layer(s)
    persist.record_step(s)
    target = s.directory
    if tamper == "symlink":
        link = tmp_path / "link"
        link.symlink_to(s.directory, target_is_directory=True)
        target = link
    elif tamper == "mode":
        os.chmod(s.directory, 0o755)
    elif tamper == "cwd":
        progress = s.directory / "progress.json"
        data = json.loads(progress.read_text())
        data["cwds"][-1] = "../../etc"
        progress.write_text(json.dumps(data))
    elif tamper == "gap":
        (s.directory / "layers" / "005" / "upper").mkdir(parents=True)
    elif tamper == "workspace":
        meta = s.directory / "meta.json"
        data = json.loads(meta.read_text())
        data["workspace"] = "/"
        meta.write_text(json.dumps(data))
    with pytest.raises(persist.SessionStateError):
        persist.load_session(target)


def test_layer_directories_are_private(tmp_path):
    s = _open(tmp_path)
    upper = layers.new_layer(s)
    for path in (s.directory / "layers", upper.parent, upper, upper.parent / "work"):
        assert path.stat().st_mode & 0o777 == 0o700, path


def test_lock_is_exclusive(tmp_path):
    s = _open(tmp_path)
    with persist.session_lock(s.directory):
        with pytest.raises(persist.SessionBusy):
            with persist.session_lock(s.directory, wait=False):
                pass
    with persist.session_lock(s.directory, wait=False):
        pass


def test_find_session_by_id_under_state_root(tmp_path):
    s = _open(tmp_path)
    assert persist.find_session(s.directory.name, tmp_path / "state") == s.directory
    with pytest.raises(persist.SessionStateError):
        persist.find_session("../escape", tmp_path / "state")
