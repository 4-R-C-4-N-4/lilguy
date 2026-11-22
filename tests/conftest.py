"""All tests are offline; data fetching is an explicit CLI operation."""
import socket

import pytest


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
