"""Fail-closed regressions for capability reporting."""
import subprocess

import pytest

from lilguy import probe


@pytest.mark.parametrize("abi", [-1, 0])
def test_missing_landlock_is_required_failure(monkeypatch, abi):
    monkeypatch.setattr(probe, "_current_arch", lambda: "x86_64")
    monkeypatch.setattr(probe, "_landlock_abi_raw", lambda _: abi)
    result = probe.check_landlock()
    assert result.required is True
    assert result.status == "fail"


@pytest.mark.parametrize("check,marker", [(probe.check_overlay_userns, "WHITEOUT_OK"),
                                          (probe.check_stacked_overlay, "STACKED_OK")])
def test_overlay_nonzero_never_passes_on_success_marker(monkeypatch, check, marker):
    monkeypatch.setattr(probe, "_run", lambda *a, **k: subprocess.CompletedProcess([], 1, marker, "cleanup failed"))
    assert check().status == "fail"


def test_bwrap_stat_failure_is_not_reported_nonsetuid(monkeypatch):
    monkeypatch.setattr(probe, "_run", lambda *a, **k: subprocess.CompletedProcess([], 0, "bubblewrap 0.12.0", ""))
    def denied(*args, **kwargs):
        raise PermissionError("cannot inspect executable")
    monkeypatch.setattr(probe.os, "stat", denied)
    assert probe.check_bwrap_version().status == "fail"


def test_probe_rejects_unknown_option():
    with pytest.raises(SystemExit) as exc:
        probe.main(["--typo"])
    assert exc.value.code == 2
