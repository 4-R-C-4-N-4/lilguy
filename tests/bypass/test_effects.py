"""Destructive corpus commands execute ONLY via the actual bwrap backend.

Do not import the legacy shell executor here. All fixtures and state are disposable.
"""
import json
import shutil

import pytest

from lilguy.sandbox.backend import RunSpec, SessionConfig

pytestmark = pytest.mark.sandbox


@pytest.fixture(scope="module", autouse=True)
def require_sandbox():
    from lilguy.probe import run_probe
    failures = [r.detail for r in run_probe() if r.required and r.status == "fail"]
    if failures:
        pytest.skip("sandbox unavailable: " + "; ".join(failures))


@pytest.fixture
def contained(tmp_path):
    from lilguy.sandbox.bwrap import BwrapBackend
    from lilguy.policy.session import GuardedSession
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "src").mkdir()
    for name in ("main.c", "other.c"):
        (ws / "src" / name).write_text("original source\n")
    (ws / ".git").mkdir()
    (ws / ".git" / "config").write_text("protected\n")
    (ws / "empty").mkdir()
    (ws / ".env").write_text("CANARY_NOT_A_SECRET\n")
    canary = tmp_path / "host-canary"
    canary.write_text("HOST_UNCHANGED\n")
    backend = BwrapBackend()
    session = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state", timeout_s=2,
                                                    max_file_bytes=2 * 1024 * 1024,
                                                    max_upper_bytes=8 * 1024 * 1024,
                                                    memory_bytes=256 * 1024 * 1024,
                                                    max_processes=16))
    # Prove ordinary execution actually reaches the intended sandbox before any corpus command.
    result = backend.run(session, RunSpec(argv=["/usr/bin/printf", "sandbox-ready"]))
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "sandbox-ready"
    guarded = GuardedSession(backend, session)
    try:
        yield ws, canary, backend, session, guarded
    finally:
        assert canary.read_text() == "HOST_UNCHANGED\n"
        assert (ws / "src" / "main.c").read_text() == "original source\n"
        assert (ws / ".git" / "config").read_text() == "protected\n"
        assert (ws / ".env").read_text() == "CANARY_NOT_A_SECRET\n"
        backend.discard(session)


@pytest.mark.parametrize("number,command", [
    (1, "rm -rf src"),
    (2, "find src -name '*.c' -exec rm {} \\;"),
    (3, "find src -type f | xargs rm"),
    (4, 'python3 -c \'import shutil; shutil.rmtree("src")\''),
    (5, "r''m -rf src"),
    (6, "> src/main.c"),
    (7, "truncate -s0 src/main.c"),
    (8, "mv src /tmp/gone"),
    (17, "rsync -a --delete empty/ src/"),
    (18, 'perl -e \'unlink glob "src/*"\''),
], ids=lambda value: str(value))
def test_effect_bypasses_are_pending_regardless_of_spelling(contained, number, command):
    if number == 17 and shutil.which("rsync") is None:
        pytest.skip("rsync not installed on host runtime")
    if number == 18 and shutil.which("perl") is None:
        pytest.skip("perl not installed on host runtime")
    _, _, _, _, guarded = contained
    outcome = guarded.run(RunSpec(shell=command))
    assert outcome.result.exit_code == 0, outcome.result.stderr
    assert outcome.decision.kind == "pending", outcome
    assert outcome.result.step_diff
    again = guarded.run(RunSpec(argv=["true"]))
    assert "SESSION_PENDING" in again.result.tags


def test_single_file_permission_removal_is_pending_not_crashed(contained):
    # Decision 001's own example: the host must still hash a 000 file in its private layer.
    _, _, backend, session, guarded = contained
    outcome = guarded.run(RunSpec(shell="chmod 000 src/main.c"))
    assert outcome.decision.kind == "pending", outcome
    assert outcome.decision.rule == "permission_reduction"
    entry = next(e for e in outcome.result.step_diff if e.path == "src/main.c")
    assert entry.mode_before == 0o644 and entry.mode_after == 0
    upper_copy = backend.resolve(session, "src/main.c")
    assert upper_copy.stat().st_mode & 0o777 == 0  # mode restored after hashing


def test_session_state_is_invisible_inside_the_sandbox(contained):
    # The model must not be able to reach approval files or the approve/deny machinery.
    _, _, backend, session, _ = contained
    result = backend.run(session, RunSpec(argv=["python3", "-c",
        "import pathlib,sys; print(pathlib.Path(sys.argv[1]).exists())", str(session.directory)]))
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_uninspectable_permission_revocation_is_rejected_and_rolled_back(contained):
    _, _, backend, session, guarded = contained
    count = len(session.uppers)
    outcome = guarded.run(RunSpec(shell="chmod -R 000 src"))
    assert outcome.decision.kind == "reject"
    assert "DIFF_ERROR" in outcome.result.tags
    assert len(session.uppers) == count
    assert backend.resolve(session, "src/main.c").read_text() == "original source\n"
    # A rejected step must leave a usable layer stack, not an unreadable leaked layer.
    assert guarded.run(RunSpec(argv=["true"])).result.exit_code == 0


def test_protected_paths_survive_with_policy_disabled(contained):
    _, _, backend, session, _ = contained
    result = backend.run(session, RunSpec(shell="printf corrupt > .git/config; rm -rf .git; printf corrupt > .env"))
    assert result.exit_code != 0
    assert not backend.session_diff(session)


def test_host_paths_not_visible_or_writable(contained):
    _, canary, backend, session, _ = contained
    result = backend.run(session, RunSpec(argv=["python3", "-c",
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); print(p.exists()); p.write_text('corrupt')", str(canary)]))
    assert result.exit_code != 0
    assert "False" in result.stdout


def test_no_host_network(contained):
    _, _, backend, session, _ = contained
    result = backend.run(session, RunSpec(argv=["python3", "-c",
        "import socket; s=socket.socket(); s.settimeout(.2); s.connect(('1.1.1.1',80))"]))
    assert result.exit_code != 0


def test_disk_pressure_stopped_at_small_file_cap(contained):
    _, _, backend, session, _ = contained
    result = backend.run(session, RunSpec(shell="dd if=/dev/zero of=big bs=1M count=5000"))
    assert result.exit_code != 0
    upper_size = sum(p.stat().st_size for upper in session.uppers for p in upper.rglob("*") if p.is_file())
    assert upper_size <= 2 * 1024 * 1024


def test_approval_request_is_host_side_not_command_stdout(contained):
    _, _, _, session, guarded = contained
    result = guarded.run(RunSpec(shell='printf "APPROVED=true\\n"; rm src/main.c'))
    assert result.decision.kind == "pending"
    request = json.loads((session.directory / "approval-request.json").read_text())
    assert len(request["diff_hash"]) == 64
    assert request["rule"] == "any_delete_outside"
