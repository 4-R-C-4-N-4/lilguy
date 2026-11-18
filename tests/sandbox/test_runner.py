"""Real-bwrap TDD suite for the P1 sandbox runner.

Every test here spawns an actual bubblewrap process; the whole module is
marked ``sandbox`` and skips (with the probe's reason) if the host can't
run the real sandbox. No mocking of bwrap itself -- that would just test
our argv-building logic, not that containment actually holds.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from lilguy.probe import run_probe
from lilguy.sandbox import limits
from lilguy.sandbox.backend import RunSpec, SessionConfig
from lilguy.sandbox.bwrap import validate_workspace
from lilguy.sandbox.runner import BwrapBackend

_PROBE_RESULTS = run_probe()
_PROBE_FAILURES = [r for r in _PROBE_RESULTS if r.required and r.status == "fail"]

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


@pytest.fixture
def backend():
    return BwrapBackend()


def _cfg(**kw) -> SessionConfig:
    return SessionConfig(**kw)


# ---------------------------------------------------------------------------
# Basic argv echo inside a real bwrap sandbox
# ---------------------------------------------------------------------------


def test_argv_echo_runs_inside_bwrap(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        r = backend.run(s, RunSpec(argv=["echo", "hello-from-sandbox"]))
        assert r.exit_code == 0
        assert r.stdout.strip() == "hello-from-sandbox"
    finally:
        backend.discard(s)


def test_exit_code_propagates(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        r = backend.run(s, RunSpec(argv=["sh", "-c", "exit 7"]))
        assert r.exit_code == 7
    finally:
        backend.discard(s)


# ---------------------------------------------------------------------------
# Overlay isolation: host workspace must be untouched
# ---------------------------------------------------------------------------


def test_writes_land_in_overlay_not_host_workspace(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        r = backend.run(s, RunSpec(argv=["sh", "-c", "echo written > new.txt"]))
        assert r.exit_code == 0
        assert not (workspace / "new.txt").exists(), "host workspace must stay pristine"
        # but is visible in the overlay via resolve()
        resolved = backend.resolve(s, "new.txt")
        assert resolved is not None and resolved.read_text().strip() == "written"
    finally:
        backend.discard(s)


def test_deleting_pre_existing_file_does_not_touch_host(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        r = backend.run(s, RunSpec(argv=["rm", "hello.txt"]))
        assert r.exit_code == 0
        assert (workspace / "hello.txt").exists(), "host file must survive an in-sandbox rm"
    finally:
        backend.discard(s)


def test_second_step_sees_first_steps_write(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        backend.run(s, RunSpec(argv=["sh", "-c", "echo one > a.txt"]))
        r = backend.run(s, RunSpec(argv=["cat", "a.txt"]))
        assert r.exit_code == 0
        assert r.stdout.strip() == "one"
    finally:
        backend.discard(s)


def test_stacked_overlay_whiteout_hides_base_file_across_steps(backend, workspace):
    """Empirical check: deleting in step N must stay deleted in step N+1."""
    s = backend.open_session(workspace, _cfg())
    try:
        r1 = backend.run(s, RunSpec(argv=["rm", "hello.txt"]))
        assert r1.exit_code == 0
        r2 = backend.run(s, RunSpec(argv=["sh", "-c", "test -e hello.txt && echo PRESENT || echo GONE"]))
        assert r2.stdout.strip() == "GONE"
    finally:
        backend.discard(s)


# ---------------------------------------------------------------------------
# Namespace isolation
# ---------------------------------------------------------------------------


def test_network_is_unreachable(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        r = backend.run(s, RunSpec(
            argv=["sh", "-c", "exec 3<>/dev/tcp/127.0.0.1/1 2>&1 || echo NO_NET"],
            timeout_s=5,
        ))
        assert "NO_NET" in r.stdout or r.exit_code != 0
    finally:
        backend.discard(s)


def test_pid_namespace_sandbox_sees_itself_as_pid1(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        r = backend.run(s, RunSpec(argv=["sh", "-c", "echo $$"]))
        assert r.exit_code == 0
        assert r.stdout.strip().isdigit() and int(r.stdout.strip()) <= 4
    finally:
        backend.discard(s)


def test_host_home_is_not_visible(backend, workspace):
    s = backend.open_session(workspace, _cfg(mount_path="short"))
    try:
        r = backend.run(s, RunSpec(argv=["sh", "-c", "echo $HOME"]))
        assert r.exit_code == 0
        assert r.stdout.strip() == "/home/sandbox"
        r2 = backend.run(s, RunSpec(argv=["sh", "-c", "ls /home"]))
        assert r2.stdout.strip() == "sandbox"
    finally:
        backend.discard(s)


# ---------------------------------------------------------------------------
# Protected paths
# ---------------------------------------------------------------------------


def test_git_directory_is_read_only(backend, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".git").mkdir()
    (ws / ".git" / "config").write_text("original\n")
    s = backend.open_session(ws, _cfg())
    try:
        r = backend.run(s, RunSpec(argv=["sh", "-c", "echo bad > .git/config 2>&1; echo exit=$?"]))
        assert "exit=0" not in r.stdout
        assert (ws / ".git" / "config").read_text() == "original\n"
    finally:
        backend.discard(s)


def test_env_file_is_read_only_regardless_of_policy(backend, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".env").write_text("SECRET=1\n")
    s = backend.open_session(ws, _cfg())
    try:
        r = backend.run(s, RunSpec(argv=["sh", "-c", "echo x > .env 2>&1; echo exit=$?"]))
        assert "exit=0" not in r.stdout
    finally:
        backend.discard(s)


# ---------------------------------------------------------------------------
# Timeout and output truncation
# ---------------------------------------------------------------------------


def test_timeout_kills_the_sandbox_process_tree(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        start = time.monotonic()
        r = backend.run(s, RunSpec(argv=["sleep", "30"], timeout_s=2))
        elapsed = time.monotonic() - start
        assert "TIMEOUT" in r.tags
        assert elapsed < 15
    finally:
        backend.discard(s)


def test_output_is_truncated_to_cap(backend, workspace):
    cfg = _cfg(max_output_bytes=1000)
    s = backend.open_session(workspace, cfg)
    try:
        r = backend.run(s, RunSpec(argv=["sh", "-c", "yes x | head -c 100000"]))
        assert len(r.stdout.encode("utf-8", errors="ignore")) <= 1000
        assert "OUTPUT_TRUNCATED" in r.tags
    finally:
        backend.discard(s)


# ---------------------------------------------------------------------------
# cwd tracking
# ---------------------------------------------------------------------------


def test_cwd_persists_across_steps(backend, workspace):
    (workspace / "sub").mkdir()
    s = backend.open_session(workspace, _cfg())
    try:
        r1 = backend.run(s, RunSpec(shell="cd sub && pwd"))
        assert r1.cwd == "sub"
        r2 = backend.run(s, RunSpec(argv=["pwd"]))
        assert r2.stdout.strip().endswith("/sub")
    finally:
        backend.discard(s)


def test_cwd_report_cannot_escape_via_stdout_spoof(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        # The program prints a fake absolute path to stdout; that must have
        # zero effect on bookkeeping since cwd comes from a separate fd,
        # not stdout parsing.
        r = backend.run(s, RunSpec(argv=["sh", "-c", "echo /etc/passwd"]))
        assert r.cwd == "."
    finally:
        backend.discard(s)


# ---------------------------------------------------------------------------
# Shell / pipe modes through the same runner
# ---------------------------------------------------------------------------


def test_shell_mode(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        r = backend.run(s, RunSpec(shell="echo $((2+2))"))
        assert r.exit_code == 0
        assert r.stdout.strip() == "4"
    finally:
        backend.discard(s)


def test_pipe_mode(backend, workspace):
    s = backend.open_session(workspace, _cfg())
    try:
        r = backend.run(s, RunSpec(pipe=[["echo", "hello world"], ["wc", "-w"]]))
        assert r.exit_code == 0
        assert r.stdout.strip() == "2"
    finally:
        backend.discard(s)


# ---------------------------------------------------------------------------
# Workspace root rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_root", ["/", "/usr", "/home", "/etc"])
def test_dangerous_workspace_roots_are_rejected(bad_root):
    with pytest.raises(ValueError):
        validate_workspace(Path(bad_root))


def test_valid_disposable_workspace_is_accepted(workspace):
    assert validate_workspace(workspace) == Path(os.path.realpath(workspace))


def test_workspace_overlapping_state_dir_is_rejected(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    state = ws / "state"
    state.mkdir()
    with pytest.raises(ValueError):
        validate_workspace(ws, state_dir=state)


# ---------------------------------------------------------------------------
# Max layers fail-closed
# ---------------------------------------------------------------------------


def test_max_layers_fails_closed(backend, workspace):
    cfg = _cfg(max_layers=2)
    s = backend.open_session(workspace, cfg)
    try:
        r1 = backend.run(s, RunSpec(argv=["true"]))
        assert r1.exit_code == 0
        r2 = backend.run(s, RunSpec(argv=["true"]))
        assert r2.exit_code == 0
        assert len(s.uppers) == 2
        r3 = backend.run(s, RunSpec(argv=["true"]))
        assert "MAX_LAYERS" in r3.tags
        assert r3.exit_code == -1
        assert len(s.uppers) == 2
    finally:
        backend.discard(s)


# ---------------------------------------------------------------------------
# Disk caps: periodic monitoring during the step, not just a post-step check
# ---------------------------------------------------------------------------


def test_disk_cap_stops_a_long_running_write_early(backend, workspace):
    cfg = _cfg(max_upper_bytes=512_000, timeout_s=20)
    s = backend.open_session(workspace, cfg)
    try:
        start = time.monotonic()
        r = backend.run(s, RunSpec(
            shell="dd if=/dev/zero of=big.bin bs=1M count=200 2>/dev/null; sleep 20",
            timeout_s=20,
        ))
        elapsed = time.monotonic() - start
        assert "DISK_CAP" in r.tags
        # Caught by the live monitor, not the 20s timeout/post-step check.
        assert elapsed < 15
    finally:
        backend.discard(s)


def test_single_file_cap_stops_early(backend, workspace):
    cfg = _cfg(max_file_bytes=256_000, max_upper_bytes=50 * 1024 * 1024, timeout_s=10)
    s = backend.open_session(workspace, cfg)
    try:
        r = backend.run(s, RunSpec(
            shell="dd if=/dev/zero of=one.bin bs=1M count=200 2>&1; echo rc=$?",
            timeout_s=10,
        ))
        assert backend.resolve(s, "one.bin") is not None or "DISK_CAP" in r.tags
        resolved = backend.resolve(s, "one.bin")
        if resolved is not None:
            assert resolved.stat().st_size <= cfg.max_file_bytes
    finally:
        backend.discard(s)


# ---------------------------------------------------------------------------
# Cgroup containment proof
# ---------------------------------------------------------------------------


def test_cgroup_scope_actually_applies_memory_max(workspace):
    """Real proof, not a mock: read the live cgroup's memory.max from the
    host filesystem, for the exact scope the runner wraps a step in, while
    that step is still running. The sandboxed process has no visibility of
    /sys/fs/cgroup itself (it's not bound into bwrap at all); the proof has
    to come from the host side, reading only this one disposable scope.
    """
    if not limits.cgroup_scope_available():
        pytest.skip("systemd-run --user --scope unavailable on this host")
    cfg = _cfg(memory_bytes=257 * 1024 * 1024, max_processes=16)
    argv = limits.wrap_with_cgroup_scope(["sleep", "5"], cfg, unit_prefix="lilguy-cgroup-proof")
    unit = next(a.split("=", 1)[1] for a in argv if a.startswith("--unit=")) + ".scope"
    proc = subprocess.Popen(argv)
    try:
        memory_max = None
        for _ in range(40):
            out = subprocess.run(
                ["systemctl", "--user", "show", unit, "-p", "MemoryMax", "-p", "SubState"],
                capture_output=True, text=True,
            ).stdout
            if "running" in out:
                memory_max = next(
                    (line.split("=", 1)[1] for line in out.splitlines() if line.startswith("MemoryMax=")),
                    None,
                )
                if memory_max and memory_max != "infinity":
                    break
            time.sleep(0.1)
        assert memory_max is not None and memory_max != "infinity", "scope never showed a live MemoryMax"
        assert int(memory_max) == cfg.memory_bytes
    finally:
        proc.kill()
        proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Destructive-bypass canary: a real host path outside the workspace must
# never be touched, even if sandbox construction is attempted against it.
# ---------------------------------------------------------------------------


def test_host_canary_outside_workspace_survives_full_suite(workspace):
    canary = Path(tempfile.gettempdir()) / "lilguy-canary-outside-ws.txt"
    canary.write_text("untouched\n")
    try:
        backend = BwrapBackend()
        s = backend.open_session(workspace, _cfg())
        try:
            backend.run(s, RunSpec(argv=["sh", "-c", f"rm -f {canary} 2>/dev/null; true"]))
        finally:
            backend.discard(s)
        assert canary.exists()
        assert canary.read_text() == "untouched\n"
    finally:
        canary.unlink(missing_ok=True)
