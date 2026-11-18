"""Real-bwrap TDD suite for progress-aware liveness in BwrapBackend.run().

Mirrors test_runner.py's skip-if-no-bwrap discipline. No mocking of bwrap,
systemd-run or the cgroup filesystem -- these tests exercise the real thing.
"""
from __future__ import annotations

import subprocess
import time

import pytest

from lilguy.probe import run_probe
from lilguy.sandbox.backend import RunSpec, SessionConfig
from lilguy.sandbox.runner import BwrapBackend

_PROBE_FAILURES = [r for r in run_probe() if r.required and r.status == "fail"]

pytestmark = pytest.mark.sandbox

if _PROBE_FAILURES:
    pytest.skip(
        "real sandbox capability probe failed: "
        + "; ".join(f"{r.name}: {r.detail}" for r in _PROBE_FAILURES),
        allow_module_level=True,
    )


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "hello.txt").write_text("hi\n")
    return ws


def _cfg(**kw) -> SessionConfig:
    return SessionConfig(**kw)


def _no_active_scopes():
    deadline = time.monotonic() + 3
    out = ""
    while time.monotonic() < deadline:
        out = subprocess.run(
            ["systemctl", "--user", "list-units", "lilguy-sandbox-*", "--state=active", "--no-legend"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5,
        ).stdout
        if out.strip() == "":
            return
        time.sleep(0.1)
    assert out.strip() == "", f"leftover active scopes: {out!r}"


@pytest.fixture(autouse=True)
def _check_no_leftover_scopes():
    # Machine-wide check: it also sees scopes from another concurrent pytest run, so do not
    # run the live sandbox suites in parallel (a false failure was seen that way once).
    yield
    _no_active_scopes()


def test_idle_timeout_keeps_partial_work(workspace):
    backend = BwrapBackend()
    s = backend.open_session(workspace, _cfg(idle_timeout_s=1, timeout_s=10))
    try:
        start = time.monotonic()
        r = backend.run(s, RunSpec(shell="printf partial > kept.txt; sleep 30"))
        elapsed = time.monotonic() - start
        assert "IDLE_TIMEOUT" in r.tags
        assert elapsed < 10
        assert any(e.path == "kept.txt" for e in r.step_diff)
        assert s.uppers, "layer must be kept, not rolled back"
        resolved = backend.resolve(s, "kept.txt")
        assert resolved is not None and resolved.read_text() == "partial"
        assert (workspace / "kept.txt").exists() is False
    finally:
        backend.discard(s)


def test_stall_stop_without_monitor(workspace):
    backend = BwrapBackend()
    s = backend.open_session(workspace, _cfg(stall_timeout_s=1, timeout_s=10))
    try:
        start = time.monotonic()
        r = backend.run(s, RunSpec(shell="printf x > before.txt; while :; do :; done"))
        elapsed = time.monotonic() - start
        assert "STALLED" in r.tags
        assert elapsed < 10
        assert any(e.path == "before.txt" for e in r.step_diff)
    finally:
        backend.discard(s)


def test_progress_extends_beyond_stall_and_idle_timeouts(workspace):
    backend = BwrapBackend()
    s = backend.open_session(workspace, _cfg(stall_timeout_s=1, idle_timeout_s=1, timeout_s=10))
    try:
        r = backend.run(s, RunSpec(shell=(
            "for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do "
            "printf x > f$i.txt; sleep 0.2; done"
        )))
        assert r.exit_code == 0
        assert not (set(r.tags) & {"TIMEOUT", "IDLE_TIMEOUT", "STALLED"})
    finally:
        backend.discard(s)


def test_freeze_and_ask_then_stop(workspace):
    calls = []

    class Monitor:
        def heartbeat(self, status):
            pass

        def stalled(self, status):
            calls.append(status)
            cg = subprocess.run(
                ["systemctl", "--user", "list-units", "lilguy-sandbox-*", "--state=active", "--no-legend"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5,
            ).stdout
            unit = cg.split()[0] if cg.strip() else None
            if unit:
                path = subprocess.run(
                    ["systemctl", "--user", "show", unit, "-p", "ControlGroup", "--value"],
                    stdout=subprocess.PIPE, text=True, timeout=5,
                ).stdout.strip()
                frozen_file = f"/sys/fs/cgroup{path}/cgroup.freeze"
                try:
                    # cgroup.freeze flips to "1" once the freezer has actually
                    # stopped the tasks, which can lag the freeze request by a
                    # beat -- poll briefly instead of asserting immediately.
                    for _ in range(20):
                        with open(frozen_file) as fh:
                            if fh.read().strip() == "1":
                                break
                        time.sleep(0.02)
                    else:
                        raise AssertionError("cgroup never reported frozen")
                except OSError:
                    pass
                cpu_file = f"/sys/fs/cgroup{path}/cpu.stat"
                try:
                    def _usage_usec(text):
                        for line in text.splitlines():
                            if line.startswith("usage_usec"):
                                return line.split()[1]
                        return None
                    with open(cpu_file) as fh:
                        before = _usage_usec(fh.read())
                    time.sleep(0.3)
                    with open(cpu_file) as fh:
                        after = _usage_usec(fh.read())
                    assert before == after, "cpu usage must not advance while frozen"
                except OSError:
                    pass
            return "continue" if len(calls) == 1 else "stop"

    backend = BwrapBackend(monitor=Monitor())
    s = backend.open_session(workspace, _cfg(stall_timeout_s=1, timeout_s=15))
    try:
        r = backend.run(s, RunSpec(shell="while :; do :; done"))
        assert len(calls) == 2
        assert "STALLED" in r.tags
    finally:
        backend.discard(s)


def test_frozen_time_excluded_from_hard_wall():
    class Monitor:
        first = True

        def heartbeat(self, status):
            pass

        def stalled(self, status):
            if Monitor.first:
                Monitor.first = False
                time.sleep(2)
                return "continue"
            return "stop"

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        ws.mkdir()
        backend = BwrapBackend(monitor=Monitor())
        s = backend.open_session(ws, _cfg(stall_timeout_s=1, timeout_s=3))
        try:
            r = backend.run(s, RunSpec(shell="while :; do :; done"))
            assert "STALLED" in r.tags
            assert "TIMEOUT" not in r.tags
        finally:
            backend.discard(s)


def test_heartbeat_called_with_increasing_elapsed(workspace):
    heartbeats = []

    class Monitor:
        def heartbeat(self, status):
            heartbeats.append(status)

        def stalled(self, status):
            return "stop"

    backend = BwrapBackend(monitor=Monitor())
    s = backend.open_session(workspace, _cfg(heartbeat_s=0.5, timeout_s=10))
    try:
        backend.run(s, RunSpec(shell=(
            "for i in 1 2 3 4 5 6 7 8 9 10; do printf x > g$i.txt; sleep 0.2; done"
        )))
        assert len(heartbeats) >= 2
        assert all(h.state == "running" for h in heartbeats)
        elapsed = [h.elapsed_s for h in heartbeats]
        assert elapsed == sorted(elapsed)
        assert elapsed[-1] > elapsed[0]
    finally:
        backend.discard(s)


def test_hard_wall_still_kills_a_progressing_loop(workspace):
    backend = BwrapBackend()
    s = backend.open_session(workspace, _cfg(timeout_s=2, stall_timeout_s=30, idle_timeout_s=30))
    try:
        start = time.monotonic()
        r = backend.run(s, RunSpec(shell="i=0; while :; do echo line$i; i=$((i+1)); sleep 0.1; done"))
        elapsed = time.monotonic() - start
        assert "TIMEOUT" in r.tags
        assert elapsed < 10
        assert s.uppers, "partial layer must be kept on hard-wall timeout too"
    finally:
        backend.discard(s)


def test_monitor_exception_in_stalled_treated_as_stop(workspace):
    class Monitor:
        def heartbeat(self, status):
            pass

        def stalled(self, status):
            raise RuntimeError("boom")

    backend = BwrapBackend(monitor=Monitor())
    s = backend.open_session(workspace, _cfg(stall_timeout_s=1, timeout_s=10))
    try:
        r = backend.run(s, RunSpec(shell="while :; do :; done"))
        assert "STALLED" in r.tags
    finally:
        backend.discard(s)
