"""Network in the real sandbox: off by default; a networked step reaches the network but not host IPC."""
import os
import socket
import threading

import pytest

from lilguy.sandbox.backend import RunSpec, SessionConfig

pytestmark = pytest.mark.sandbox

PROBE = r"""
import socket, sys
kind, target = sys.argv[1], sys.argv[2]
try:
    if kind == "tcp":
        s = socket.create_connection(("127.0.0.1", int(target)), timeout=3)
        print("connected", s.recv(16).decode())
    else:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect("\0" + target)
        print("connected", s.recv(16).decode())
except OSError as exc:
    print("blocked", exc.errno)
"""


def _serve(sock):
    def loop():
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            conn.sendall(b"hello")
            conn.close()
    threading.Thread(target=loop, daemon=True).start()


@pytest.fixture
def host_services():
    tcp = socket.socket()
    tcp.bind(("127.0.0.1", 0))
    tcp.listen()
    name = f"lilguy-test-{os.getpid()}-{os.urandom(4).hex()}"
    abstract = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    abstract.bind("\0" + name)
    abstract.listen()
    _serve(tcp)
    _serve(abstract)
    yield tcp.getsockname()[1], name
    tcp.close()
    abstract.close()


@pytest.fixture
def sandbox(tmp_path):
    from lilguy.sandbox.bwrap import BwrapBackend
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "probe.py").write_text(PROBE)
    backend = BwrapBackend()
    session = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state", timeout_s=30))
    yield backend, session
    backend.discard(session)


def _probe(backend, session, kind, target, network):
    result = backend.run(session, RunSpec(argv=["python3", "probe.py", kind, str(target)], network=network))
    assert result.exit_code == 0, (result.tags, result.stderr)
    return result


def test_ordinary_step_has_no_network(sandbox, host_services):
    backend, session = sandbox
    port, _ = host_services
    assert _probe(backend, session, "tcp", port, False).stdout.startswith("blocked")


def test_networked_step_reaches_the_network(sandbox, host_services):
    backend, session = sandbox
    port, _ = host_services
    result = _probe(backend, session, "tcp", port, True)
    assert result.stdout.strip() == "connected hello"
    assert "NETWORK" in result.tags


def test_networked_step_cannot_reach_host_abstract_sockets(sandbox, host_services):
    backend, session = sandbox
    _, name = host_services
    # Sanity: the host side really is listening (checked from a subprocess; the in-process test
    # guard blocks socket connects, and this is a local socket, not network).
    import subprocess
    import sys
    check = subprocess.run([sys.executable, "-c", PROBE, "unix", name], capture_output=True, text=True)
    assert check.stdout.strip() == "connected hello", check
    assert _probe(backend, session, "unix", name, True).stdout.startswith("blocked")


def test_networked_step_is_still_file_sandboxed(sandbox):
    backend, session = sandbox
    result = backend.run(session, RunSpec(shell="echo hi > made.txt && ls /home", network=True))
    assert result.exit_code == 0, result.stderr
    assert not (session.workspace / "made.txt").exists()
    assert any(e.path == "made.txt" for e in result.step_diff)


def test_cli_ask_approve_once_then_run(tmp_path, host_services, monkeypatch, capsys):
    import json

    from tests.sandbox.test_cli_flow import lilguy
    port, _ = host_services
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "probe.py").write_text(PROBE)
    cmd = f"python3 probe.py tcp {port}"
    code, out, err = lilguy(monkeypatch, capsys, "sandbox-run", "--workspace", str(ws), "--state-dir",
                            str(tmp_path / "state"), "--keep", "--network", "--cmd", cmd)
    assert code == 2 and "needs network" in err
    session = json.loads(out)["session_path"]
    code, out, err = lilguy(monkeypatch, capsys, "approve", session)
    assert code == 1 and "--diff-hash" in err      # no terminal: must name the reviewed request
    digest = out.strip().splitlines()[-1].split()[-1]
    assert lilguy(monkeypatch, capsys, "approve", session, "--diff-hash", digest)[0] == 0
    code, out, err = lilguy(monkeypatch, capsys, "sandbox-run", "--session", session, "--network", "--cmd", cmd)
    assert code == 0, err
    assert json.loads(out)["result"]["stdout"].strip() == "connected hello"
    code, out, err = lilguy(monkeypatch, capsys, "sandbox-run", "--session", session, "--network", "--cmd", cmd)
    assert code == 2  # the grant was for one step only
