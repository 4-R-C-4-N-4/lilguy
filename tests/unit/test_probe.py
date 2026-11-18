"""Tests for lilguy.probe (P0 capability probe).

Live checks (unshare/overlay/bwrap/landlock/systemd-run) actually exercise the host;
only failure-path behaviour of individual check functions is mocked. ``main()`` is
also run live at least once to prove the real end-to-end probe executes.
"""
from __future__ import annotations

import subprocess


import pytest

from lilguy import probe


# ---------------------------------------------------------------------------
# CheckResult / data shape
# ---------------------------------------------------------------------------


def test_check_result_fields():
    r = probe.CheckResult(name="kernel", required=True, status="pass", detail="6.18.0")
    assert r.name == "kernel"
    assert r.required is True
    assert r.status == "pass"
    assert r.detail == "6.18.0"


def test_check_result_status_must_be_valid():
    with pytest.raises(ValueError):
        probe.CheckResult(name="x", required=True, status="maybe", detail="")


# ---------------------------------------------------------------------------
# Individual checks: architecture guard before landlock syscall
# ---------------------------------------------------------------------------


def test_landlock_check_unsupported_arch_fails_without_syscall(monkeypatch):
    """On an architecture without a known landlock syscall number, the check
    must short-circuit to a warning and never attempt the raw syscall."""
    monkeypatch.setattr(probe, "_LANDLOCK_SYSCALL_NRS", {}, raising=False)
    called = {"n": 0}

    def fake_syscall(*a, **k):
        called["n"] += 1
        return -1

    monkeypatch.setattr(probe, "_landlock_abi_raw", fake_syscall)
    result = probe.check_landlock()
    assert called["n"] == 0
    assert result.status == "fail"
    assert result.required is True


def test_landlock_check_abi_0_is_fail_like_warn(monkeypatch):
    monkeypatch.setattr(probe, "_LANDLOCK_SYSCALL_NRS", {"x86_64": 444}, raising=False)
    monkeypatch.setattr(probe, "_current_arch", lambda: "x86_64")
    monkeypatch.setattr(probe, "_landlock_abi_raw", lambda nr: 0)
    result = probe.check_landlock()
    assert result.status in ("warn", "fail")


def test_landlock_check_abi_low_warns_truncate_tcp(monkeypatch):
    monkeypatch.setattr(probe, "_LANDLOCK_SYSCALL_NRS", {"x86_64": 444}, raising=False)
    monkeypatch.setattr(probe, "_current_arch", lambda: "x86_64")
    monkeypatch.setattr(probe, "_landlock_abi_raw", lambda nr: 2)
    result = probe.check_landlock()
    assert result.status == "warn"
    assert "truncate" in result.detail.lower() or "tcp" in result.detail.lower()


def test_landlock_check_abi_high_passes(monkeypatch):
    monkeypatch.setattr(probe, "_LANDLOCK_SYSCALL_NRS", {"x86_64": 444}, raising=False)
    monkeypatch.setattr(probe, "_current_arch", lambda: "x86_64")
    monkeypatch.setattr(probe, "_landlock_abi_raw", lambda nr: 7)
    result = probe.check_landlock()
    assert result.status == "pass"


def test_kernel_version_check_parses_release(monkeypatch):
    class FakeUname:
        release = "5.10.0-generic"

    monkeypatch.setattr(probe.os, "uname", lambda: FakeUname())
    result = probe.check_kernel_version()
    assert result.required is True
    assert result.status == "fail"


def test_kernel_version_check_passes_on_recent(monkeypatch):
    class FakeUname:
        release = "6.18.52-1-lts"

    monkeypatch.setattr(probe.os, "uname", lambda: FakeUname())
    result = probe.check_kernel_version()
    assert result.status == "pass"


def test_unprivileged_userns_check_subprocess_failure(monkeypatch):
    def fake_run(*a, **k):
        raise FileNotFoundError("unshare not found")

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    result = probe.check_unprivileged_userns()
    assert result.status == "fail"
    assert result.required is True


def test_unprivileged_userns_check_timeout(monkeypatch):
    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="unshare", timeout=5)

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    result = probe.check_unprivileged_userns()
    assert result.status == "fail"


def test_bwrap_version_check_setuid(monkeypatch, tmp_path):
    fake_bwrap = tmp_path / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\necho 'bubblewrap 0.11.0'\n")
    fake_bwrap.chmod(0o4755)  # setuid bit
    monkeypatch.setenv("LILGUY_BWRAP", str(fake_bwrap))

    def fake_run(argv, *a, **k):
        class R:
            returncode = 0
            stdout = "bubblewrap 0.11.0\n"
            stderr = ""

        return R()

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    result = probe.check_bwrap_version()
    assert result.status == "fail"
    assert "setuid" in result.detail.lower()


def test_bwrap_version_check_too_old(monkeypatch, tmp_path):
    fake_bwrap = tmp_path / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\n")
    fake_bwrap.chmod(0o755)
    monkeypatch.setenv("LILGUY_BWRAP", str(fake_bwrap))

    def fake_run(argv, *a, **k):
        class R:
            returncode = 0
            stdout = "bubblewrap 0.9.0\n"
            stderr = ""

        return R()

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    result = probe.check_bwrap_version()
    assert result.status == "fail"
    assert "0.11" in result.detail


def test_bwrap_version_check_missing_binary(monkeypatch):
    monkeypatch.setenv("LILGUY_BWRAP", "/nonexistent/bwrap-xyz")

    def fake_run(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    result = probe.check_bwrap_version()
    assert result.status == "fail"


def test_cgroup_delegation_is_warning_only(monkeypatch):
    def fake_run(*a, **k):
        class R:
            returncode = 1
            stdout = ""
            stderr = "failed"

        return R()

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    result = probe.check_cgroup_delegation()
    assert result.required is False
    assert result.status == "warn"


# ---------------------------------------------------------------------------
# run_probe() / main() structural + behavioural
# ---------------------------------------------------------------------------


def test_run_probe_returns_list_of_checkresult():
    results = probe.run_probe()
    assert isinstance(results, list)
    assert len(results) > 0
    for r in results:
        assert isinstance(r, probe.CheckResult)


def test_run_probe_has_expected_required_checks():
    results = probe.run_probe()
    names = {r.name for r in results}
    for expected in (
        "kernel_version",
        "unprivileged_userns",
        "overlay_userns",
        "stacked_overlay",
        "bwrap_version",
        "bwrap_overlay",
        "landlock_abi",
        "cgroup_delegation",
        "python_in_sandbox",
    ):
        assert expected in names, f"missing check {expected}"


def test_run_probe_separates_required_and_warn_only():
    results = probe.run_probe()
    by_name = {r.name: r for r in results}
    assert by_name["cgroup_delegation"].required is False
    assert by_name["kernel_version"].required is True
    assert by_name["unprivileged_userns"].required is True


def test_main_exit_code_matches_required_failures(monkeypatch, capsys):
    def fake_run_probe():
        return [
            probe.CheckResult(name="a", required=True, status="pass", detail=""),
            probe.CheckResult(name="b", required=False, status="warn", detail="meh"),
        ]

    monkeypatch.setattr(probe, "run_probe", fake_run_probe)
    code = probe.main([])
    assert code == 0


def test_main_nonzero_on_required_failure(monkeypatch):
    def fake_run_probe():
        return [
            probe.CheckResult(name="a", required=True, status="fail", detail="broke"),
            probe.CheckResult(name="b", required=False, status="warn", detail="meh"),
        ]

    monkeypatch.setattr(probe, "run_probe", fake_run_probe)
    code = probe.main([])
    assert code != 0


def test_main_prints_table(monkeypatch, capsys):
    def fake_run_probe():
        return [probe.CheckResult(name="a", required=True, status="pass", detail="ok")]

    monkeypatch.setattr(probe, "run_probe", fake_run_probe)
    probe.main([])
    out = capsys.readouterr().out
    assert "a" in out
    assert "pass" in out.lower()


def test_main_json_output(monkeypatch, capsys):
    def fake_run_probe():
        return [probe.CheckResult(name="a", required=True, status="pass", detail="ok")]

    monkeypatch.setattr(probe, "run_probe", fake_run_probe)
    probe.main(["--json"])
    out = capsys.readouterr().out
    import json

    data = json.loads(out)
    assert isinstance(data, list)
    assert data[0]["name"] == "a"
    assert data[0]["status"] == "pass"


def test_main_returns_int_not_none(monkeypatch):
    def fake_run_probe():
        return [probe.CheckResult(name="a", required=True, status="pass", detail="ok")]

    monkeypatch.setattr(probe, "run_probe", fake_run_probe)
    code = probe.main([])
    assert isinstance(code, int)


# ---------------------------------------------------------------------------
# Live, real-platform integration (no mocks): this is the actual contract.
# ---------------------------------------------------------------------------


def test_live_run_probe_executes_real_checks():
    """Run the real probe against this host. We don't assert pass/fail for every
    row (host-dependent), but the probe must execute cleanly, every row is a
    well-formed CheckResult with a valid status, and at minimum kernel_version
    (easy, deterministic on this host) actually passes."""
    results = probe.run_probe()
    by_name = {r.name: r for r in results}
    assert by_name["kernel_version"].status == "pass"
    for r in results:
        assert r.status in ("pass", "warn", "fail")


def test_live_main_runs_end_to_end_and_exit_code_is_int():
    code = probe.main(["--json"])
    assert isinstance(code, int)
