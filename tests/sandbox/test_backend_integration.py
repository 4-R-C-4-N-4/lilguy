import pytest

from lilguy.sandbox.backend import RunSpec, SessionConfig
from lilguy.sandbox.bwrap import BwrapBackend

pytestmark = pytest.mark.sandbox


def test_backend_uses_shared_private_session_layout(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    state = tmp_path / "state"
    backend = BwrapBackend()
    session = backend.open_session(ws, SessionConfig(state_dir=state))
    try:
        assert session.directory.parent == state
        assert session.uppers == []
        assert (session.directory / "commit_snapshot.json").is_file()
    finally:
        backend.discard(session)


def test_real_step_has_observed_diff_not_stub(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    backend = BwrapBackend()
    session = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    try:
        result = backend.run(session, RunSpec(argv=["/usr/bin/printf", "ready"]))
        assert result.exit_code == 0, result.stderr
        result = backend.run(session, RunSpec(shell="printf safe > added"))
        assert result.exit_code == 0, result.stderr
        assert any(e.path == "added" and e.op == "added" for e in result.step_diff)
        assert any(e.path == "added" and e.op == "added" for e in backend.session_diff(session))
        assert not (ws / "added").exists()
    finally:
        backend.discard(session)
