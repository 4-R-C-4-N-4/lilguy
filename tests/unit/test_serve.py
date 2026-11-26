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
    from lilguy.sandbox import persist
    assert seen["state_dir"] == persist.default_state_root().resolve()


def test_do_without_config_fails_before_creating_state(xdg, tmp_path, capsys, sandbox_ok):
    assert do.main(["hello", "--workspace", str(tmp_path)]) == 2
    assert "lilguy setup" in capsys.readouterr().err
    from lilguy.sandbox import persist
    assert not persist.default_state_root().exists()


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


# --- released model download --------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload):
        self._data, self._pos = payload, 0

    def read(self, n):
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _release(payload):
    import hashlib
    return {"repo": "someone/model", "file": "m.gguf", "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path / "data" / "lilguy" / "models"


def test_release_url_points_at_hugging_face():
    assert serve.release_url({"repo": "a/b", "file": "c.gguf"}) == \
        "https://huggingface.co/a/b/resolve/main/c.gguf"


def test_release_pin_is_the_evaluated_artifact():
    # sha256 of reports/factory/soup-r14-lr1e4/minicpm/tuned-q8_0.gguf (r14 soup, lr 1e-4 x2, seeds
    # 42-44), the file held-out v3 scored 86/100 on (reports/factory/held-out-zospysbm)
    assert serve.RELEASE["sha256"] == "2557103c7a05bfbbc320ffdcabeda882ec782f9815f6583cd1dce89938d2bf4d"
    assert serve.RELEASE["interface"] == 6 == serve.KNOWN_MODELS[serve.RELEASE["sha256"]]
    assert serve.KNOWN_MODELS["0d90e036f52ee7890df33e877898963d9a657785e0c4cb58532538689be8f233"] == 4  # 2.0
    assert serve.KNOWN_MODELS["5626927a90f9981d56ab94d4bed8495c183487df818af63651c4d32055b18c94"] == 3


def test_fetch_downloads_and_verifies(data_dir):
    payload = b"GGUF" * 1000
    seen = []
    path = serve.fetch_release(_release(payload), log=lambda *a, **k: None,
                               opener=lambda url, timeout: seen.append(url) or FakeResponse(payload))
    assert path == data_dir / "m.gguf" and path.read_bytes() == payload
    assert seen == ["https://huggingface.co/someone/model/resolve/main/m.gguf"]


def test_fetch_reuses_a_verified_file_without_network(data_dir):
    payload = b"GGUF-ok"
    data_dir.mkdir(parents=True)
    (data_dir / "m.gguf").write_bytes(payload)
    path = serve.fetch_release(_release(payload), log=lambda *a, **k: None,
                               opener=lambda *a, **k: pytest.fail("must not download"))
    assert path.read_bytes() == payload


def test_fetch_rejects_a_mismatched_download_and_leaves_nothing(data_dir):
    release = _release(b"the real bytes")
    with pytest.raises(serve.ServeError, match="SHA-256"):
        serve.fetch_release(release, log=lambda *a, **k: None,
                            opener=lambda url, timeout: FakeResponse(b"other bytes!!!"))
    assert not list(data_dir.iterdir())


def test_fetch_replaces_a_corrupt_local_copy(data_dir):
    payload = b"good-bytes"
    data_dir.mkdir(parents=True)
    (data_dir / "m.gguf").write_bytes(b"bad-bytes!")  # same size, wrong hash
    path = serve.fetch_release(_release(payload), log=lambda *a, **k: None,
                               opener=lambda url, timeout: FakeResponse(payload))
    assert path.read_bytes() == payload


# --- CPU mode -----------------------------------------------------------------------------

def test_cpu_mode_hides_gpus_and_offloads_nothing(cfg):
    cpu = serve.Config(cfg.model, cfg.llama_server, serve.CPU, cfg.port)
    assert serve.server_env(cpu)["CUDA_VISIBLE_DEVICES"] == ""
    assert serve.server_command(cpu)[-2:] == ["-ngl", "0"]


def test_setup_with_local_model_and_cpu_writes_config(xdg, cfg, capsys):
    code = serve.setup_main(["--model", str(cfg.model), "--llama-server", str(cfg.llama_server),
                             "--cpu", "--port", "18999", "--interface", "4"])
    assert code == 0, capsys.readouterr().err
    loaded = serve.load_config()
    assert loaded.gpu == serve.CPU and loaded.model == cfg.model.resolve() and loaded.interface == 4
    assert "lilguy demo" in capsys.readouterr().out


def test_setup_without_model_downloads_the_release(xdg, cfg, monkeypatch, capsys):
    monkeypatch.setattr(serve, "fetch_release", lambda: cfg.model)
    assert serve.setup_main(["--llama-server", str(cfg.llama_server), "--cpu"]) == 0
    assert serve.load_config().model == cfg.model


def test_setup_explains_missing_llama_server(xdg, monkeypatch, capsys):
    monkeypatch.setattr(serve, "find_llama_server", lambda: None)
    assert serve.setup_main(["--cpu"]) == 2
    assert "llama.cpp" in capsys.readouterr().err


def test_setup_refuses_an_unknown_model_without_an_interface(xdg, cfg, capsys):
    assert serve.setup_main(["--model", str(cfg.model), "--llama-server", str(cfg.llama_server), "--cpu"]) == 2
    assert "--interface" in capsys.readouterr().err


def test_setup_detects_the_interface_of_a_known_release_file(xdg, cfg, monkeypatch):
    import hashlib
    monkeypatch.setitem(serve.KNOWN_MODELS, hashlib.sha256(b"GGUF").hexdigest(), 4)
    assert serve.setup_main(["--model", str(cfg.model), "--llama-server", str(cfg.llama_server), "--cpu"]) == 0
    assert serve.load_config().interface == 4


def test_configs_from_1x_without_interface_mean_v3(xdg, cfg):
    path = serve.write_config(cfg)
    path.write_text("\n".join(line for line in path.read_text().splitlines() if not line.startswith("interface")))
    assert serve.load_config().interface == 3


def test_do_drives_the_configured_interface(xdg, cfg, tmp_path, monkeypatch):
    import dataclasses
    seen = {}
    monkeypatch.setattr(do, "check_sandbox", lambda: None)
    monkeypatch.setattr(serve, "load_config", lambda: dataclasses.replace(cfg, interface=4))
    monkeypatch.setattr(serve, "ensure_server", lambda c: "http://127.0.0.1:18999")

    def fake_drive(request, workspace, state_dir, **kw):
        seen["version"] = kw["version"]
        raise do.DoSafetyError("stop here")
    monkeypatch.setattr(do, "drive", fake_drive)
    do.main(["hello", "--workspace", str(tmp_path)])
    assert seen["version"] == 4
