"""Spec §12 corpus #9 and #19, executed only in the real bubblewrap backend on disposable fixtures."""
from pathlib import Path

import pytest

from lilguy.policy.engine import Policy
from lilguy.sandbox.backend import RunSpec, SessionConfig

pytestmark = pytest.mark.sandbox


@pytest.fixture(scope="module", autouse=True)
def require_sandbox():
    from lilguy.probe import run_probe
    failures = [r.detail for r in run_probe() if r.required and r.status == "fail"]
    if failures:
        pytest.skip("sandbox unavailable: " + "; ".join(failures))


def _open(tmp_path, files):
    from lilguy.sandbox.bwrap import BwrapBackend
    ws = tmp_path / "workspace"
    (ws / "src").mkdir(parents=True)
    for i in range(files):
        (ws / "src" / f"f{i:02d}.c").write_text(f"file {i}\n")
    backend = BwrapBackend()
    session = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state", timeout_s=20,
                                                    max_processes=16, memory_bytes=256 * 1024 * 1024))
    return ws, backend, session


def _preflight(backend, session, ws):
    """Harmless check that must pass before any destructive command runs in this session."""
    real_home = Path.home().resolve()
    check = backend.run(session, RunSpec(argv=["python3", "-c", (
        "import os,sys,pathlib\n"
        "home=pathlib.Path(sys.argv[1]); ws=pathlib.Path(sys.argv[2])\n"
        "print(os.environ.get('HOME'))\n"
        "on_path={ws.parents[i] for i in range(len(ws.parents))} | {ws}\n"
        "print(sorted(str(home/n) for n in os.listdir(home) if (home/n) not in on_path) if home.exists() else [])\n"
        "try:\n open('/usr/lilguy-write-test','w'); print('usr-writable')\n"
        "except OSError: print('usr-readonly')\n"), str(real_home), str(ws)]))
    assert check.exit_code == 0, check.stderr
    home_env, visible, usr = check.stdout.splitlines()
    assert home_env == "/home/sandbox"
    assert visible == "[]", f"real home contents visible in sandbox: {visible}"
    assert usr == "usr-readonly"
    # The preflight wrote nothing; drop its layer so the corpus step is judged alone.
    backend.rollback_step(session)


def test_19_deletions_spread_over_steps_trip_the_session_total(tmp_path):
    from lilguy.policy.session import GuardedSession
    ws, backend, session = _open(tmp_path, 45)
    # Trusted config that turns off per-delete approval, so the session total is what decides.
    guarded = GuardedSession(backend, session, policies=[Policy(any_delete_outside=None)])
    try:
        first = guarded.run(RunSpec(shell="rm src/f0[0-9].c src/f1[0-4].c"))
        assert first.decision.kind == "ok", first
        second = guarded.run(RunSpec(shell="rm src/f1[5-9].c src/f2[0-9].c"))
        assert (second.decision.kind, second.decision.rule) == ("pending", "max_deletes"), second
        assert "SESSION_PENDING" in guarded.run(RunSpec(argv=["true"])).result.tags
        assert len(list((ws / "src").iterdir())) == 45  # nothing reached the real workspace
    finally:
        backend.discard(session)


def test_9_rm_rf_home_and_root_stays_inside_the_sandbox(tmp_path):
    from lilguy.policy.session import GuardedSession
    ws, backend, session = _open(tmp_path, 3)
    canary = tmp_path / "host-canary"
    canary.write_text("HOST_UNCHANGED\n")
    guarded = GuardedSession(backend, session)
    try:
        _preflight(backend, session, ws)

        outcome = guarded.run(RunSpec(shell="rm -rf ~ /"))
        assert outcome.decision.kind in ("pending", "ok", "reject"), outcome
        assert canary.read_text() == "HOST_UNCHANGED\n"
        assert sorted(p.name for p in (ws / "src").iterdir()) == ["f00.c", "f01.c", "f02.c"]
        assert Path("/usr/bin/env").exists()
        # GNU rm refuses "/" (--preserve-root); ~ is the sandbox's private home, so no workspace
        # file is deleted and there is nothing to approve.
        assert "preserve-root" in outcome.result.stderr or "dangerous" in outcome.result.stderr
        assert not [e for e in outcome.result.step_diff if e.op == "deleted"]
    finally:
        backend.discard(session)


def test_9_variant_without_preserve_root_still_cannot_reach_the_host(tmp_path):
    from lilguy.policy.session import GuardedSession
    ws, backend, session = _open(tmp_path, 3)
    canary = tmp_path / "host-canary"
    canary.write_text("HOST_UNCHANGED\n")
    guarded = GuardedSession(backend, session)
    try:
        _preflight(backend, session, ws)
        outcome = guarded.run(RunSpec(shell="rm -rf --no-preserve-root / 2>/dev/null; ls src | wc -l"))
        assert canary.read_text() == "HOST_UNCHANGED\n"
        assert sorted(p.name for p in (ws / "src").iterdir()) == ["f00.c", "f01.c", "f02.c"]
        # Inside the sandbox the workspace copy is gone, so the step is a set of deletions to review.
        assert outcome.decision.kind == "pending", outcome
        assert {e.path for e in outcome.result.step_diff if e.op == "deleted"} >= {"src/f00.c", "src"}
    finally:
        backend.discard(session)
