"""`lilguy setup` / `lilguy serve` / `lilguy stop`: one owner for lilguy's local model server.

The tuned checkpoint is only meaningful behind lilguy (protocol, sandbox, request settings),
and lilguy is only meaningful in front of that checkpoint. This module ties them together:

- `lilguy setup` downloads the released model (pinned by SHA-256) unless `--model GGUF` is
  given, finds llama-server, and writes one config (model, llama-server, GPU or CPU, port).
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
SERVER_FLAGS = ["-c", "4096", "-np", "1"]
CPU = "cpu"
_START_TIMEOUT = 180.0

# The released model: the exact bytes the round reports and the safety gate were run against.
RELEASE = {
    "repo": "4rc4n4/lilguy-minicpm5-2b-GGUF",
    "file": "lilguy-v1-minicpm5-2b-q8_0.gguf",
    "sha256": "5626927a90f9981d56ab94d4bed8495c183487df818af63651c4d32055b18c94",
    "bytes": 2679706816,
}


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


def data_home() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "lilguy"


def _pid_file() -> Path:
    return state_home() / "server.json"


# --- config ------------------------------------------------------------------------------

def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ServeError(f"no lilguy config at {path}; run: lilguy setup") from None
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


# --- the released model ------------------------------------------------------------------

def release_url(release: dict = RELEASE) -> str:
    return f"https://huggingface.co/{release['repo']}/resolve/main/{release['file']}"


def sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_release(release: dict = RELEASE, log=print, opener=None) -> Path:
    """The released GGUF under the XDG data dir, downloaded once and always hash-checked.

    A file whose SHA-256 differs from the pin is never used: a partial or substituted
    download fails here rather than becoming a model lilguy silently drives."""
    target = data_home() / "models" / release["file"]
    if target.is_file() and target.stat().st_size == release["bytes"]:
        log(f"Checking {target} ...", file=sys.stderr)
        if sha256_file(target) == release["sha256"]:
            return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    url = release_url(release)
    log(f"Downloading {url} ({release['bytes'] / 2**30:.2f} GiB) ...", file=sys.stderr)
    import hashlib
    digest, done, shown = hashlib.sha256(), 0, -1
    try:
        with (opener or urllib.request.urlopen)(url, timeout=60) as resp, part.open("wb") as out:
            for block in iter(lambda: resp.read(1 << 20), b""):
                out.write(block)
                digest.update(block)
                done += len(block)
                pct = done * 100 // max(release["bytes"], 1)
                if pct // 10 != shown:
                    shown = pct // 10
                    log(f"  {pct:3d}%", file=sys.stderr)
    except (urllib.error.URLError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise ServeError(f"download failed: {exc}") from None
    if digest.hexdigest() != release["sha256"]:
        part.unlink(missing_ok=True)
        raise ServeError(f"downloaded file does not match the pinned SHA-256 {release['sha256']}")
    part.replace(target)
    return target


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
    if cfg.gpu == CPU:
        env["CUDA_VISIBLE_DEVICES"] = ""
    elif cfg.gpu:
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        env["CUDA_VISIBLE_DEVICES"] = gpu_index(cfg.gpu)
    return env


def server_command(cfg: Config) -> list[str]:
    return [str(cfg.llama_server), "-m", str(cfg.model),
            "--host", "127.0.0.1", "--port", str(cfg.port), *SERVER_FLAGS,
            "-ngl", "0" if cfg.gpu == CPU else "all"]


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
    where = "CPU" if cfg.gpu == CPU else f"GPU {cfg.gpu}" if cfg.gpu else "default device"
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
    ap = argparse.ArgumentParser(prog="lilguy setup", description="Download lilguy's model and write its config.")
    ap.add_argument("--model", type=Path, default=None,
                    help=f"use a local GGUF instead of downloading {RELEASE['repo']}")
    ap.add_argument("--llama-server", type=Path, default=None,
                    help="llama-server binary (default: PATH, then ~/programs/llama.cpp/build/bin)")
    device = ap.add_mutually_exclusive_group()
    device.add_argument("--gpu", default=None, help="NVIDIA GPU name to pin, e.g. 4070 (default: any)")
    device.add_argument("--cpu", action="store_true", help="run on the CPU only (slower, no GPU needed)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)
    server = args.llama_server or find_llama_server()
    if server is None:
        print("lilguy setup: llama-server not found. Install llama.cpp "
              "(https://github.com/ggml-org/llama.cpp) and put llama-server on PATH, "
              "or pass --llama-server PATH", file=sys.stderr)
        return 2
    try:
        model = args.model.expanduser().resolve() if args.model else fetch_release()
    except ServeError as exc:
        print(f"lilguy setup: {exc}", file=sys.stderr)
        return 2
    cfg = Config(model=model, llama_server=server.expanduser().resolve(),
                 gpu=CPU if args.cpu else args.gpu, port=args.port)
    try:
        if not cfg.model.is_file():
            raise ServeError(f"model not found: {cfg.model}")
        if not os.access(cfg.llama_server, os.X_OK):
            raise ServeError(f"llama-server not executable: {cfg.llama_server}")
        device = ("CPU" if cfg.gpu == CPU else _verify_device(cfg) if cfg.gpu
                  else "default device (llama.cpp's choice)")
    except ServeError as exc:
        print(f"lilguy setup: {exc}", file=sys.stderr)
        return 2
    path = write_config(cfg)
    print(f"Wrote {path}\n  model:  {cfg.model}\n  server: {cfg.llama_server}\n"
          f"  device: {device}\n  url:    {cfg.url}\n"
          "Next: lilguy demo   (makes a practice folder and shows what to try)")
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
    print(f"lilguy serve: {cfg.model.name} on {cfg.url} ({cfg.gpu or 'default device'})", flush=True)
    os.execve(str(cfg.llama_server), server_command(cfg), env)
    return 0  # pragma: no cover


def stop_main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="lilguy stop",
                            description="Stop the model server lilguy ask/do started.").parse_args(argv)
    print(stop_server())
    return 0
