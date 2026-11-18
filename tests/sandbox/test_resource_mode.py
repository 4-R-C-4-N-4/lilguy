"""Resource-mode availability must be explicit before launching any payload."""
from unittest.mock import Mock

import pytest

from lilguy.sandbox import limits, runner
from lilguy.sandbox.backend import RunSpec, SessionConfig

pytestmark = pytest.mark.sandbox


def test_cgroup_availability_is_cached_per_session_not_per_step(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    calls = []
    original = limits.cgroup_scope_available
    def probe():
        calls.append(True)
        return original()
    monkeypatch.setattr(limits, "cgroup_scope_available", probe)
    backend = runner.BwrapBackend()
    session = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    try:
        for _ in range(2):
            assert backend.run(session, RunSpec(argv=["true"])).exit_code == 0
        assert len(calls) == 1
    finally:
        backend.discard(session)


def test_explicit_rlimits_fallback_is_visible_and_keeps_cwd(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    backend = runner.BwrapBackend()
    # The availability proof is taken at session open, so patch it first.
    monkeypatch.setattr(limits, "cgroup_scope_available", lambda: False)
    session = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state", allow_rlimits_fallback=True))
    wrapper = Mock(side_effect=AssertionError("unavailable scope must not be invoked"))
    monkeypatch.setattr(limits, "wrap_with_cgroup_scope", wrapper)
    try:
        result = backend.run(session, RunSpec(shell="cd sub; printf fallback"))
        assert result.exit_code == 0, result.stderr
        assert "DEGRADED_RLIMITS" in result.tags
        assert result.cwd == "sub"
        wrapper.assert_not_called()
    finally:
        backend.discard(session)


def test_wrapper_cannot_vanish_after_availability_proof(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    backend = runner.BwrapBackend()
    session = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    monkeypatch.setattr(limits, "cgroup_scope_available", lambda: True)
    monkeypatch.setattr(limits, "wrap_with_cgroup_scope", lambda argv, *_: argv)
    launcher = Mock(side_effect=AssertionError("must refuse an unwrapped payload"))
    monkeypatch.setattr(runner.subprocess, "Popen", launcher)
    try:
        with pytest.raises(RuntimeError, match="refusing unscoped"):
            backend.run(session, RunSpec(argv=["true"]))
        launcher.assert_not_called()
        assert session.uppers == []
    finally:
        backend.discard(session)


def test_unavailable_cgroup_refuses_payload_by_default(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    backend = runner.BwrapBackend()
    monkeypatch.setattr(limits, "cgroup_scope_available", lambda: False)
    session = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    monkeypatch.setattr(limits, "wrap_with_cgroup_scope", lambda argv, *_: argv)
    launcher = Mock(side_effect=AssertionError("payload must not be launched without cgroup proof"))
    monkeypatch.setattr(runner.subprocess, "Popen", launcher)
    try:
        result = backend.run(session, RunSpec(argv=["true"]))
        assert result.exit_code != 0
        assert "CGROUP_UNAVAILABLE" in result.tags
        launcher.assert_not_called()
        assert session.uppers == []
    finally:
        backend.discard(session)
