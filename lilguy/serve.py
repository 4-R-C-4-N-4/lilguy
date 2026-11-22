"""`lilguy setup` / `lilguy serve` / `lilguy stop`: one owner for lilguy's local model server.

The tuned checkpoint is only meaningful behind lilguy (protocol, sandbox, request settings),
and lilguy is only meaningful in front of that checkpoint. This module ties them together:

- `lilguy setup --model GGUF --gpu 4070` writes one config (model, llama-server, GPU, port).
- `lilguy ask|do` with no `--url` start the configured server on demand and refuse to talk
  to anything else listening on that port (e.g. another `llm` model on a shared port).
- `lilguy serve` runs it in the foreground; `lilguy stop` stops the one `ask|do` started.

Server flags mirror the evaluator (`dev/fast12_runner.managed_server`): the scores in the
round reports were measured with exactly these; sampling, seed and thinking-off travel
in each request (`do._chat_complete`). The GPU is pinned by *name* under PCI bus order,
because CUDA's default order and nvidia-smi's disagree on this host.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 18088
SERVER_FLAGS = ["-c", "4096", "-np", "1", "-ngl", "all"]
_START_TIMEOUT = 180.0


class ServeError(RuntimeError):
    """Configuration or server state lilguy cannot trust; print and stop."""


@dataclass(frozen=True)
class Config:
    model: Path
    llama_server: Path
    gpu: str | None = None
    port: int = DEFAULT_PORT

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


# --- locations ---------------------------------------------------------------------------

def config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / "lilguy" / "config.toml"


def state_home() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "state") / "lilguy"


def _pid_file() -> Path:
    return state_home() / "server.json"


# --- config ------------------------------------------------------------------------------

def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ServeError(f"no lilguy config at {path}; run: lilguy setup --model PATH.gguf") from None
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ServeError(f"cannot read {path}: {exc}") from None
    try:
        cfg = Config(model=Path(raw["model"]).expanduser(),
                     llama_server=Path(raw["llama_server"]).expanduser(),
                     gpu=raw.get("gpu") or None, port=int(raw.get("port", DEFAULT_PORT)))
    except (KeyError, TypeError, ValueError) as exc:
        raise ServeError(f"{path}: missing or invalid setting: {exc}") from None
    for label, file in (("model", cfg.model), ("llama_server", cfg.llama_server)):
        if not file.is_file():
            raise ServeError(f"{path}: {label} not found: {file}")
    return cfg


def write_config(cfg: Config, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"model = {json.dumps(str(cfg.model))}",
             f"llama_server = {json.dumps(str(cfg.llama_server))}",
             f"port = {cfg.port}"]
    if cfg.gpu:
        lines.insert(2, f"gpu = {json.dumps(cfg.gpu)}")
    path.write_text("# written by `lilguy setup`\n" + "\n".join(lines) + "\n")
    return path


def find_llama_server() -> Path | None:
    on_path = shutil.which("llama-server")
    if on_path:
        return Path(on_path)
    guess = Path.home() / "programs" / "llama.cpp" / "build" / "bin" / "llama-server"
    return guess if guess.is_file() else None


# --- GPU pinning -------------------------------------------------------------------------

def gpu_index(name: str, smi_output: str | None = None) -> str:
    """PCI-ordered index of the one GPU whose name contains `name` (case-insensitive)."""
    if smi_output is None:
        try:
            smi_output = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader"],
                capture_output=True, text=True, check=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise ServeError(f"cannot list GPUs with nvidia-smi: {exc}") from None
    rows = [line.split(",", 1) for line in smi_output.strip().splitlines() if "," in line]
    hits = [(i.strip(), n.strip()) for i, n in rows if name.lower() in n.lower()]
    if len(hits) != 1:
        found = ", ".join(n.strip() for _, n in rows) or "none"
        raise ServeError(f"gpu {name!r} must match exactly one GPU; found: {found}")
    return hits[0][0]


def server_env(cfg: Config) -> dict[str, str]:
    env = dict(os.environ)
    if cfg.gpu:
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        env["CUDA_VISIBLE_DEVICES"] = gpu_index(cfg.gpu)
    return env


def server_command(cfg: Config) -> list[str]:
    return [str(cfg.llama_server), "-m", str(cfg.model),
            "--host", "127.0.0.1", "--port", str(cfg.port), *SERVER_FLAGS]


# --- the running server ------------------------------------------------------------------

def served_model(url: str, timeout: float = 2.0) -> str | None:
    """Model id the server at `url` reports, or None if nothing usable answers."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{url}/v1/models", timeout=timeout) as resp:
            data = json.load(resp)
        return str(data["data"][0]["id"])
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def is_configured_model(served: str, cfg: Config) -> bool:
    try:
        return Path(served).samefile(cfg.model)
    except OSError:
        return False


def ensure_server(cfg: Config, log=print) -> str:
    """URL of a server running exactly the configured model; start one if none is up."""
    served = served_model(cfg.url)
    if served is not None:
        if is_configured_model(served, cfg):
            return cfg.url
        raise ServeError(f"port {cfg.port} is serving {served}, not lilguy's model {cfg.model}; "
                         f"stop it or change `port` in {config_path()}")
    env = server_env(cfg)
    state_home().mkdir(parents=True, exist_ok=True)
    log_path = state_home() / "server.log"
    where = f"GPU {cfg.gpu}" if cfg.gpu else "default GPU"
    log(f"Starting lilguy model on {where} (port {cfg.port}; stop with: lilguy stop) ...",
        file=sys.stderr)
    with log_path.open("w") as out:
        proc = subprocess.Popen(server_command(cfg), env=env, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    _pid_file().write_text(json.dumps({"pid": proc.pid, "port": cfg.port, "model": str(cfg.model)}))
    deadline = time.monotonic() + _START_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _pid_file().unlink(missing_ok=True)
            raise ServeError(f"llama-server exited with {proc.returncode}; see {log_path}")
        served = served_model(cfg.url, timeout=1.0)
        if served is not None and _healthy(cfg.url):
            if not is_configured_model(served, cfg):
                raise ServeError(f"port {cfg.port} answered with {served}; see {log_path}")
            return cfg.url
        time.sleep(0.25)
    proc.terminate()
    _pid_file().unlink(missing_ok=True)
    raise ServeError(f"llama-server did not become ready in {_START_TIMEOUT:.0f}s; see {log_path}")


def _healthy(url: str) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{url}/health", timeout=1.0) as resp:
            return json.load(resp).get("status") == "ok"
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return False


def stop_server() -> str:
    """Stop the server `ensure_server` started; never signal a process it did not start."""
    try:
        info = json.loads(_pid_file().read_text())
        pid = int(info["pid"])
    except FileNotFoundError:
        return "no lilguy-started server is recorded"
    except (OSError, ValueError, KeyError, TypeError):
        _pid_file().unlink(missing_ok=True)
        return "discarded an unreadable server record"
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        cmdline = []
    if str(info.get("model", "")).encode() not in cmdline:
        _pid_file().unlink(missing_ok=True)
        return f"server pid {pid} is no longer running"
    os.kill(pid, signal.SIGTERM)
    _pid_file().unlink(missing_ok=True)
    return f"stopped lilguy model server (pid {pid}, port {info.get('port')})"


# --- CLI ---------------------------------------------------------------------------------

def setup_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lilguy setup", description="Write lilguy's model config.")
    ap.add_argument("--model", type=Path, required=True, help="tuned lilguy GGUF")
    ap.add_argument("--llama-server", type=Path, default=None,
                    help="llama-server binary (default: PATH, then ~/programs/llama.cpp/build/bin)")
    ap.add_argument("--gpu", default=None, help="GPU name to pin, e.g. 4070 (default: any)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)
    server = args.llama_server or find_llama_server()
    if server is None:
        print("lilguy setup: llama-server not found; pass --llama-server", file=sys.stderr)
        return 2
    cfg = Config(model=args.model.expanduser().resolve(), llama_server=server.expanduser().resolve(),
                 gpu=args.gpu, port=args.port)
    try:
        if not cfg.model.is_file():
            raise ServeError(f"model not found: {cfg.model}")
        if not os.access(cfg.llama_server, os.X_OK):
            raise ServeError(f"llama-server not executable: {cfg.llama_server}")
        device = _verify_device(cfg) if cfg.gpu else "default device"
    except ServeError as exc:
        print(f"lilguy setup: {exc}", file=sys.stderr)
        return 2
    path = write_config(cfg)
    print(f"Wrote {path}\n  model:  {cfg.model}\n  server: {cfg.llama_server}\n"
          f"  device: {device}\n  url:    {cfg.url}\n"
          "Try: lilguy ask \"what files are here?\" (starts the model on first use)")
    return 0


def _verify_device(cfg: Config) -> str:
    """Ask llama-server itself which CUDA device the pinned env exposes."""
    wanted = (cfg.gpu or "").lower()
    try:
        listing = subprocess.run([str(cfg.llama_server), "--list-devices"], env=server_env(cfg),
                                 capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServeError(f"llama-server --list-devices failed: {exc}") from None
    names = [line.split(":", 1)[1].split("(")[0].strip() for line in listing.splitlines()
             if line.strip().startswith("CUDA") and ":" in line]
    if len(names) != 1 or wanted not in names[0].lower():
        raise ServeError(f"pinned env exposes {names or 'no CUDA devices'}, expected {cfg.gpu!r}")
    return names[0]


def serve_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lilguy serve",
                                 description="Run the configured lilguy model in the foreground.")
    ap.add_argument("--port", type=int, default=None, help="override the configured port")
    args = ap.parse_args(argv)
    try:
        cfg = load_config()
        if args.port is not None:
            cfg = Config(cfg.model, cfg.llama_server, cfg.gpu, args.port)
        if served_model(cfg.url) is not None:
            raise ServeError(f"something is already serving on port {cfg.port}")
        env = server_env(cfg)
    except ServeError as exc:
        print(f"lilguy serve: {exc}", file=sys.stderr)
        return 2
    print(f"lilguy serve: {cfg.model.name} on {cfg.url} (GPU {cfg.gpu or 'default'})", flush=True)
    os.execve(str(cfg.llama_server), server_command(cfg), env)
    return 0  # pragma: no cover


def stop_main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="lilguy stop",
                            description="Stop the model server lilguy ask/do started.").parse_args(argv)
    print(stop_server())
    return 0
