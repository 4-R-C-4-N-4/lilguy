"""Run the fork-bomb corpus item only AFTER proving this exact scope's TasksMax.

No original forkbomb is ever launched on the host. The command waits inside
bubblewrap for a disposable-fixture flag which is created only after cgroup proof.
"""
import json
import subprocess
import threading
import time

import pytest

from lilguy.sandbox.backend import RunSpec, SessionConfig

pytestmark = pytest.mark.sandbox


def test_fork_bomb_is_contained_by_verified_task_scope(tmp_path, monkeypatch):
    from lilguy.sandbox import limits
    from lilguy.sandbox.bwrap import BwrapBackend
    if not limits.cgroup_scope_available():
        pytest.skip("no delegated cgroup scope; refusing to launch fork-bomb fixture")
    ws = tmp_path / "ws"
    ws.mkdir()
    canary = tmp_path / "host-canary"
    canary.write_text("unchanged")
    cfg = SessionConfig(state_dir=tmp_path / "state", timeout_s=3,
                        memory_bytes=256 * 1024 * 1024, max_processes=16,
                        max_output_bytes=8192, max_file_bytes=1024 * 1024, max_upper_bytes=4 * 1024 * 1024)
    backend = BwrapBackend()
    session = backend.open_session(ws, cfg)
    units = []
    original = limits.wrap_with_cgroup_scope
    def record_scope(*args, **kwargs):
        argv = original(*args, **kwargs)
        units.extend(a.split("=", 1)[1] for a in argv if a.startswith("--unit="))
        return argv
    monkeypatch.setattr(limits, "wrap_with_cgroup_scope", record_scope)
    outcome = []
    errors = []
    # This fixed command can start churning processes only when the parent writes go.
    command = "while [ ! -f go ]; do sleep 0.02; done\nbomb(){ bomb | bomb & }; bomb"
    def execute():
        try:
            outcome.append(backend.run(session, RunSpec(shell=command)))
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=execute)
    worker.start()
    try:
        properties = {}
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline and worker.is_alive():
            if units:
                proc = subprocess.run(["systemctl", "--user", "show", units[0] + ".scope",
                                       "-p", "TasksMax", "-p", "MemoryMax", "-p", "SubState"],
                                      capture_output=True, text=True, timeout=1)
                properties = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
                if properties.get("SubState") == "running":
                    break
            time.sleep(.02)
        assert properties.get("SubState") == "running", json.dumps(properties)
        assert int(properties["TasksMax"]) == 16
        assert int(properties["MemoryMax"]) == cfg.memory_bytes
        # Deliberately after unconditional assertions: failed proof means NO forkbomb.
        (ws / "go").write_text("verified disposable scope")
        worker.join(timeout=7)
        assert not worker.is_alive()
        assert not errors, errors
        assert outcome
        # A background fork function may return zero even when the kernel refuses
        # every further fork. Exit status alone is not containment evidence.
        assert "TIMEOUT" in outcome[0].tags or ("fork:" in outcome[0].stderr and
                                                "Resource temporarily unavailable" in outcome[0].stderr)
        inactive = False
        for _ in range(50):
            status = subprocess.run(["systemctl", "--user", "is-active", "--quiet", units[0] + ".scope"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
            if status.returncode != 0:
                inactive = True
                break
            time.sleep(.02)
        assert inactive, "transient scope retained live processes after sandbox exit"
        assert len(outcome[0].stderr.encode()) <= cfg.max_output_bytes
        assert canary.read_text() == "unchanged"
    finally:
        worker.join(timeout=7)
        assert not worker.is_alive(), "sandbox timeout failed; do not continue stress testing"
        backend.discard(session)
