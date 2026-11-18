"""Unit tests for lilguy.sandbox.limits.

These run on the *host*, never applying rlimits to the test process
itself -- rlimit_preexec_fn is only ever invoked inside a subprocess
(fork+exec), so a bug in it cannot self-restrict the test runner.
"""
from __future__ import annotations

import resource
import subprocess
import sys

import pytest

from lilguy.sandbox import limits
from lilguy.sandbox.backend import SessionConfig


def _probe_rlimits_in_subprocess(cfg: SessionConfig) -> dict:
    """Apply rlimit_preexec_fn in a real child process and report what
    RLIMIT_* ended up as, by running python -c in a subprocess with the
    preexec_fn -- never touches this test process's own limits."""
    code = (
        "import resource, json, sys\n"
        "print(json.dumps({\n"
        "    'nproc': resource.getrlimit(resource.RLIMIT_NPROC),\n"
        "    'fsize': resource.getrlimit(resource.RLIMIT_FSIZE),\n"
        "    'as_': resource.getrlimit(resource.RLIMIT_AS),\n"
        "    'core': resource.getrlimit(resource.RLIMIT_CORE),\n"
        "}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        preexec_fn=limits.rlimit_preexec_fn(cfg),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    import json as _json
    return _json.loads(proc.stdout)


def test_rlimit_preexec_caps_nproc_to_configured_absolute_value():
    cfg = SessionConfig(max_processes=7)
    result = _probe_rlimits_in_subprocess(cfg)
    soft, hard = result["nproc"]
    assert soft == 7
    assert hard == 7


def test_rlimit_preexec_sets_fsize_from_cfg():
    cfg = SessionConfig(max_file_bytes=12345)
    result = _probe_rlimits_in_subprocess(cfg)
    assert result["fsize"] == [12345, 12345]


def test_rlimit_preexec_sets_memory_as_from_cfg():
    cfg = SessionConfig(memory_bytes=999_999_999)
    result = _probe_rlimits_in_subprocess(cfg)
    assert result["as_"] == [999_999_999, 999_999_999]


def test_rlimit_preexec_disables_core_dumps():
    cfg = SessionConfig()
    result = _probe_rlimits_in_subprocess(cfg)
    assert result["core"] == [0, 0]


def test_rlimit_preexec_fn_raises_limits_error_when_kernel_refuses(monkeypatch):
    """A limit the kernel refuses to apply must not be silently swallowed."""
    cfg = SessionConfig()

    def _boom(resource_, limits_tuple):
        raise OSError("simulated refusal")

    monkeypatch.setattr(resource, "setrlimit", _boom)
    apply_fn = limits.rlimit_preexec_fn(cfg)
    with pytest.raises(limits.LimitsError):
        apply_fn()


def test_cgroup_scope_available_false_when_systemd_run_missing(monkeypatch):
    monkeypatch.setattr(limits.shutil, "which", lambda name: None)
    assert limits.cgroup_scope_available() is False


def test_cgroup_scope_available_actually_probes_not_just_which(monkeypatch):
    """Having systemd-run on PATH but a non-functional --user session
    must report unavailable, not just check os.path existence."""
    monkeypatch.setattr(limits.shutil, "which", lambda name: "/usr/bin/systemd-run")

    def _fake_run(*args, **kwargs):
        class _Result:
            returncode = 1
        return _Result()

    monkeypatch.setattr(limits.subprocess, "run", _fake_run)
    assert limits.cgroup_scope_available() is False


def test_wrap_with_cgroup_scope_uses_unique_unit_names(monkeypatch):
    monkeypatch.setattr(limits.shutil, "which", lambda name: "/usr/bin/systemd-run")
    cfg = SessionConfig()
    argv = ["true"]
    wrapped_a = limits.wrap_with_cgroup_scope(argv, cfg)
    wrapped_b = limits.wrap_with_cgroup_scope(argv, cfg)
    unit_a = next(a for a in wrapped_a if a.startswith("--unit="))
    unit_b = next(b for b in wrapped_b if b.startswith("--unit="))
    assert unit_a != unit_b


def test_wrap_with_cgroup_scope_returns_argv_unchanged_without_systemd_run(monkeypatch):
    monkeypatch.setattr(limits.shutil, "which", lambda name: None)
    cfg = SessionConfig()
    argv = ["true"]
    assert limits.wrap_with_cgroup_scope(argv, cfg) == argv
