from pathlib import Path

import pytest


def test_runspec_validates_exactly_one_mode():
    from lilguy.sandbox.backend import RunSpec
    assert RunSpec(shell="echo hi").shell == "echo hi"
    with pytest.raises(ValueError):
        RunSpec()
    with pytest.raises(ValueError):
        RunSpec(shell="true", argv=["true"])


def test_sandbox_environment_has_explicit_locale_and_terminal(tmp_path):
    from lilguy.sandbox.bwrap import build_argv
    from lilguy.sandbox.backend import SessionConfig
    argv = build_argv(workspace=tmp_path, cfg=SessionConfig(), lowers=[tmp_path],
                      upper=tmp_path / "upper", work=tmp_path / "work", entry_argv=["true"])
    env = {argv[i + 1]: argv[i + 2] for i, value in enumerate(argv) if value == "--setenv"}
    assert env["LANG"] == "C.UTF-8"
    assert env["LC_ALL"] == "C.UTF-8"
    assert env["TERM"] == "dumb"
    assert "--clearenv" in argv


def test_long_wall_budgets_are_allowed_but_bounded():
    from lilguy.sandbox.backend import MAX_WALL_S, RunSpec, SessionConfig
    assert SessionConfig().timeout_s >= 600
    assert SessionConfig(timeout_s=3600).timeout_s == 3600
    assert RunSpec(argv=["true"], timeout_s=3600).timeout_s == 3600
    for bad in (0, MAX_WALL_S + 1):
        with pytest.raises(ValueError):
            SessionConfig(timeout_s=bad)
        with pytest.raises(ValueError):
            RunSpec(argv=["true"], timeout_s=bad)
    for field in ("idle_timeout_s", "stall_timeout_s", "heartbeat_s"):
        with pytest.raises(ValueError):
            SessionConfig(**{field: 0})


def test_session_config_refuses_unsafe_limits():
    from lilguy.sandbox.backend import SessionConfig
    assert SessionConfig().mount_path == "real"
    with pytest.raises(ValueError):
        SessionConfig(timeout_s=0)
    with pytest.raises(ValueError):
        SessionConfig(state_dir=Path("relative"))
