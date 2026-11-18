"""Resource caps for sandboxed steps: rlimits + best-effort cgroup scope.

Preferred containment is a transient ``systemd-run --user --scope`` cgroup
(MemoryMax / TasksMax / CPUQuota). When that is unavailable the *caller*
must fail closed rather than silently falling back to an uncapped host
process -- this module only reports availability and wraps argv, it never
pretends a host without a usable systemd user session is fine.

``rlimit_preexec_fn`` applies rlimits inside the sandboxed child (after
Landlock, after chdir, right before exec of the untrusted command). Those
rlimits are a belt-and-suspenders layer inside the sandbox. RLIMIT_NPROC
uses real-UID/user-namespace accounting, not PID-namespace boundaries;
it must not be presented as a substitute for the exact per-step TasksMax.
Failures to apply them must not be swallowed: if the kernel refuses a
limit we are configured to enforce, that is exactly the kind of silent
non-containment this module exists to prevent.
"""
from __future__ import annotations

import resource
import shutil
import subprocess
import uuid
from typing import Callable

from lilguy.sandbox.backend import SessionConfig


class LimitsError(RuntimeError):
    """Raised when a configured resource limit cannot be applied."""


def rlimit_preexec_fn(cfg: SessionConfig) -> Callable[[], None]:
    """Return a preexec_fn applying rlimits to the about-to-exec child.

    Intended to run inside the sandbox (e.g. from landlock.py's main(),
    right before exec'ing the untrusted command), never on the host's
    systemd client or bwrap launcher. Raises LimitsError on any failure instead of
    swallowing it -- a cap we were told to enforce must either land or
    the step must not proceed.
    """

    def _apply() -> None:
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except OSError as exc:
            raise LimitsError(f"failed to set RLIMIT_CORE: {exc}") from exc
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (cfg.max_processes, cfg.max_processes))
        except OSError as exc:
            raise LimitsError(f"failed to set RLIMIT_NPROC: {exc}") from exc
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (cfg.max_file_bytes, cfg.max_file_bytes))
        except OSError as exc:
            raise LimitsError(f"failed to set RLIMIT_FSIZE: {exc}") from exc
        try:
            resource.setrlimit(resource.RLIMIT_AS, (cfg.memory_bytes, cfg.memory_bytes))
        except OSError as exc:
            raise LimitsError(f"failed to set RLIMIT_AS: {exc}") from exc

    return _apply


def cgroup_scope_available() -> bool:
    """Probe whether a usable ``systemd-run --user --scope`` exists.

    Checking that the binary merely exists on PATH is not enough: a host
    can have systemd-run installed but no usable --user session (no
    XDG_RUNTIME_DIR / dbus user bus, e.g. inside some containers or over
    a bare SSH session without a lingering session). Actually try to
    start and immediately tear down a disposable, uniquely-named no-op
    scope and check it succeeded. The result is not cached across
    process lifetimes -- a host's systemd user session availability can
    change between steps (e.g. after login), so the backend checks at launch.
    """
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        return False
    unit = f"lilguy-probe-{uuid.uuid4().hex}"
    try:
        proc = subprocess.run(
            [systemd_run, "--user", "--scope", "--quiet", "--collect", f"--unit={unit}", "--", "true"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def wrap_with_cgroup_scope(argv: list[str], cfg: SessionConfig, *, unit_prefix: str = "lilguy-sandbox") -> list[str]:
    """Prefix argv with a transient per-step systemd --user --scope cgroup.

    Each call gets a fresh ``uuid4``-derived unit name so concurrent
    sessions (which might share ``id(argv)`` across short-lived list
    objects) never collide on a unit name. Callers must check
    ``cgroup_scope_available()`` themselves and fail closed when it is
    False rather than calling this and trusting the unwrapped fallback;
    this function still returns argv unchanged in that case purely so
    callers that *do* want a graceful last-resort rlimit-only path can
    detect "no wrapping happened" by argv identity, not so it's safe to
    skip the availability check.
    """
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        return argv
    tasks_max = max(1, cfg.max_processes)
    mem_max = max(1, cfg.memory_bytes)
    unit = f"{unit_prefix}-{uuid.uuid4().hex}"
    return [
        systemd_run,
        "--user",
        "--scope",
        "--quiet",
        "--collect",
        f"--unit={unit}",
        "-p", f"MemoryMax={mem_max}",
        "-p", f"TasksMax={tasks_max}",
        "-p", "CPUQuota=200%",
        "--",
        *argv,
    ]
