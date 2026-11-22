"""Unit tests for `lilguy setup/serve/stop` and the on-demand server in `ask|do`.

No GPU, no llama-server: the network and process boundaries are stubbed. What is pinned
here is the safety-relevant behaviour: lilguy never drives a model it was not configured
with, pins the GPU by name under PCI order, and only stops a server it started itself.
"""
from __future__ import annotations

import json
import os

import pytest

from lilguy import cli, do, serve


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path


@pytest.fixture
def cfg(tmp_path):
    model = tmp_path / "lilguy.gguf"
    model.write_bytes(b"GGUF")
    server = tmp_path / "llama-server"
    server.write_text("#!/bin/sh\n")
    server.chmod(0o755)
    return serve.Config(model=model, llama_server=server, gpu="4070", port=18999)


SMI = "0, NVIDIA GeForce RTX 3090\n1, NVIDIA GeForce RTX 4070\n"


def test_config_round_trips(xdg, cfg):
    serve.write_config(cfg)
    assert serve.load_config() == cfg


def test_missing_config_points_at_setup(xdg):
    with pytest.raises(serve.ServeError, match="lilguy setup"):
        serve.load_config()


def test_config_with_missing_model_is_rejected(xdg, cfg):
    serve.write_config(cfg)
    cfg.model.unlink()
    with pytest.raises(serve.ServeError, match="model not found"):
        serve.load_config()


def test_gpu_is_pinned_by_name_in_pci_order():
    assert serve.gpu_index("4070", SMI) == "1"
    assert serve.gpu_index("rtx 3090", SMI) == "0"


@pytest.mark.parametrize("name", ["RTX", "A100"])
def test_gpu_name_must_match_exactly_one(name):
    with pytest.raises(serve.ServeError, match="exactly one GPU"):
        serve.gpu_index(name, SMI)


def test_server_env_sets_pci_order(cfg, monkeypatch):
    monkeypatch.setattr(serve, "gpu_index", lambda name: "1")
    env = serve.server_env(cfg)
    assert env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID" and env["CUDA_VISIBLE_DEVICES"] == "1"


def test_server_command_matches_evaluator_flags(cfg):
    command = serve.server_command(cfg)
    assert command[:3] == [str(cfg.llama_server), "-m", str(cfg.model)]
    assert command[-6:] == ["-c", "4096", "-np", "1", "-ngl", "all"]
    assert "127.0.0.1" in command


def test_running_configured_model_is_reused(cfg, monkeypatch):
    monkeypatch.setattr(serve, "served_model", lambda url, timeout=2.0: str(cfg.model))
    monkeypatch.setattr(serve.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start"))
    assert serve.ensure_server(cfg) == cfg.url


def test_hardlinked_model_path_counts_as_configured(cfg, tmp_path, monkeypatch):
    link = tmp_path / "other-name.gguf"
    os.link(cfg.model, link)
    monkeypatch.setattr(serve, "served_model", lambda url, timeout=2.0: str(link))
    assert serve.ensure_server(cfg) == cfg.url


def test_refuses_a_different_model_on_the_port(cfg, monkeypatch):
    monkeypatch.setattr(serve, "served_model", lambda url, timeout=2.0: "/models/gemma.gguf")
    monkeypatch.setattr(serve.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start"))
    with pytest.raises(serve.ServeError, match="not lilguy's model"):
        serve.ensure_server(cfg)


class FakeProc:
    pid = 4242
    returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15


def test_starts_server_when_none_is_up(xdg, cfg, monkeypatch):
    answers = iter([None, None, str(cfg.model)])
    started = {}
    monkeypatch.setattr(serve, "served_model", lambda url, timeout=2.0: next(answers))
    monkeypatch.setattr(serve, "_healthy", lambda url: True)
    monkeypatch.setattr(serve, "gpu_index", lambda name: "1")
    monkeypatch.setattr(serve.time, "sleep", lambda s: None)

    def popen(command, env, **kw):
        started.update(command=command, env=env, kw=kw)
        return FakeProc()
    monkeypatch.setattr(serve.subprocess, "Popen", popen)
    assert serve.ensure_server(cfg, log=lambda *a, **k: None) == cfg.url
    assert started["env"]["CUDA_VISIBLE_DEVICES"] == "1"
    assert started["kw"]["start_new_session"] is True
    assert json.loads((serve.state_home() / "server.json").read_text())["pid"] == 4242


def test_start_failure_reports_log(xdg, cfg, monkeypatch):
    proc = FakeProc()
    proc.returncode = 1
    monkeypatch.setattr(serve, "served_model", lambda url, timeout=2.0: None)
    monkeypatch.setattr(serve, "gpu_index", lambda name: "1")
    monkeypatch.setattr(serve.subprocess, "Popen", lambda *a, **k: proc)
    with pytest.raises(serve.ServeError, match="server.log"):
        serve.ensure_server(cfg, log=lambda *a, **k: None)
    assert not (serve.state_home() / "server.json").exists()


def test_stop_never_signals_an_unrelated_process(xdg, monkeypatch):
    serve.state_home().mkdir(parents=True)
    (serve.state_home() / "server.json").write_text(
        json.dumps({"pid": os.getpid(), "port": 1, "model": "/nowhere/lilguy.gguf"}))
    monkeypatch.setattr(serve.os, "kill", lambda *a: pytest.fail("must not signal"))
    assert "no longer running" in serve.stop_server()


def test_stop_with_nothing_recorded(xdg):
    assert "no lilguy-started server" in serve.stop_server()


def test_cli_dispatches_server_commands(monkeypatch):
    calls = []
    for name in ("setup", "serve", "stop"):
        monkeypatch.setattr(serve, f"{name}_main", lambda argv, n=name: calls.append((n, argv)) or 0)
    for name in ("setup", "serve", "stop"):
        assert cli.main([name, "--x"]) == 0
    assert calls == [("setup", ["--x"]), ("serve", ["--x"]), ("stop", ["--x"])]


# --- ask/do wiring ----------------------------------------------------------------------

@pytest.fixture(autouse=False)
def sandbox_ok(monkeypatch):
    monkeypatch.setattr(do, "check_sandbox", lambda: None)


def test_do_without_url_uses_configured_server_and_fresh_state(xdg, cfg, tmp_path, monkeypatch,
                                                                sandbox_ok):
    seen = {}
    monkeypatch.setattr(serve, "load_config", lambda: cfg)
    monkeypatch.setattr(serve, "ensure_server", lambda c: "http://127.0.0.1:18999")

    def fake_drive(request, workspace, state_dir, **kw):
        seen.update(state_dir=state_dir, url=kw["url"])
        raise do.DoSafetyError("stop here")
    monkeypatch.setattr(do, "drive", fake_drive)
    assert do.main(["hello", "--workspace", str(tmp_path)]) == 2
    assert seen["url"] == "http://127.0.0.1:18999"
    assert seen["state_dir"].parent == serve.state_home().resolve() / "runs"


def test_do_without_config_fails_before_creating_state(xdg, tmp_path, capsys, sandbox_ok):
    assert do.main(["hello", "--workspace", str(tmp_path)]) == 2
    assert "lilguy setup" in capsys.readouterr().err
    assert not (serve.state_home() / "runs").exists()


def test_explicit_url_bypasses_config(xdg, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(serve, "load_config", lambda: pytest.fail("explicit --url needs no config"))

    def fake_drive(request, workspace, state_dir, **kw):
        seen["url"] = kw["url"]
        raise do.DoSafetyError("stop here")
    monkeypatch.setattr(do, "drive", fake_drive)
    do.main(["hi", "--workspace", str(tmp_path), "--state-dir", str(tmp_path / "s"),
             "--url", "http://127.0.0.1:1"])
    assert seen["url"] == "http://127.0.0.1:1"
