"""All tests are offline; data fetching is an explicit CLI operation."""
import socket
from pathlib import Path

import pytest

_SANDBOX_DIR = Path(__file__).parent / "sandbox"


def pytest_collection_modifyitems(config, items):
    """Every tests/sandbox/*_live.py drives the real sandbox: mark it so a host without one
    (e.g. GitHub's runners, where unprivileged user namespaces are restricted) skips it
    instead of failing, without each new file having to remember `pytestmark`."""
    for item in items:
        path = Path(str(item.fspath))
        if path.parent == _SANDBOX_DIR and path.name.endswith("_live.py"):
            item.add_marker(pytest.mark.sandbox)


@pytest.fixture(scope="session")
def sandbox_capabilities():
    from lilguy.probe import run_probe
    return run_probe()


@pytest.fixture(autouse=True)
def require_sandbox_for_marked_tests(request):
    if request.node.get_closest_marker("sandbox"):
        results = request.getfixturevalue("sandbox_capabilities")
        failures = [f"{r.name}: {r.detail}" for r in results if r.required and r.status == "fail"]
        if failures:
            pytest.skip("sandbox unavailable: " + "; ".join(failures))


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network access is forbidden in tests")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture(autouse=True)
def isolate_lilguy_config(tmp_path_factory, monkeypatch):
    """No test reads the developer's ~/.config/lilguy (which would point at a real model)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg-config")))


@pytest.fixture(autouse=True)
def isolate_lilguy_data(tmp_path_factory, monkeypatch):
    """No test reads or downloads into the developer's ~/.local/share/lilguy."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path_factory.mktemp("xdg-data")))


@pytest.fixture(autouse=True)
def isolate_lilguy_state(tmp_path_factory, monkeypatch):
    """No test writes sessions, records or server files into the developer's ~/.local/state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path_factory.mktemp("xdg-state")))
