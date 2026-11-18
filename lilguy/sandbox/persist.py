"""Reloadable session state for trusted host processes (continue / approve / deny).

Everything here lives in the private session directory, outside the workspace
and never mounted into the sandbox. Reloading re-validates every field rather
than trusting what is on disk: a tampered or loosened session is refused.
"""
from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath

from .backend import Session, SessionConfig

_ID = re.compile(r"^\d+-[0-9a-f]{16}$")
_LAYER = re.compile(r"^\d{3}$")


class SessionStateError(Exception):
    """Session state is missing, unsafe or inconsistent; refuse to use it."""


class SessionBusy(Exception):
    """Another trusted process holds the session lock."""


def _write_json(path: Path, data) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise SessionStateError(f"missing {path.name}") from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise SessionStateError(f"{path.name} is not a regular file owned by you")
    try:
        return json.loads(path.read_text())
    except ValueError as exc:
        raise SessionStateError(f"corrupt {path.name}: {exc}") from None


def save_config(session: Session) -> None:
    cfg = dataclasses.asdict(session.cfg)
    cfg["state_dir"] = str(cfg["state_dir"]) if cfg["state_dir"] is not None else None
    cfg["protected"] = list(cfg["protected"])
    _write_json(session.directory / "config.json", cfg)
    _write_json(session.directory / "progress.json", {"cwds": [], "generation": 0})


def _safe_cwd(value) -> str:
    if not isinstance(value, str):
        raise SessionStateError("invalid cwd")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise SessionStateError(f"unsafe cwd {value!r}")
    return pure.as_posix() or "."


def generation(directory: Path) -> int:
    value = _read_json(Path(directory) / "progress.json").get("generation")
    if type(value) is not int or value < 0:
        raise SessionStateError("invalid generation")
    return value


def record_step(session: Session) -> int:
    """Record the cwd for each live layer after a step (or rollback); returns the new generation."""
    progress = _read_json(session.directory / "progress.json")
    cwds = list(progress.get("cwds", []))[:len(session.uppers)]
    while len(cwds) < len(session.uppers):
        cwds.append(_safe_cwd(session.cwd))
    new_generation = int(progress.get("generation", 0)) + 1
    _write_json(session.directory / "progress.json", {"cwds": cwds, "generation": new_generation})
    return new_generation


def _check_private_dir(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise SessionStateError(f"no such session: {path}") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise SessionStateError(f"{path} is not a real directory")
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SessionStateError(f"{path} must be private (0700) and owned by you")


def load_session(directory: Path) -> Session:
    directory = Path(directory)
    if not directory.is_absolute():
        raise SessionStateError("session directory must be absolute")
    _check_private_dir(directory)
    meta = _read_json(directory / "meta.json")
    raw_cfg = _read_json(directory / "config.json")
    progress = _read_json(directory / "progress.json")
    if not (directory / "commit_snapshot.json").is_file():
        raise SessionStateError("missing opening snapshot")

    workspace = Path(meta.get("workspace", ""))
    from .bwrap import validate_workspace
    try:
        workspace = validate_workspace(workspace, directory.parent)
    except ValueError as exc:
        raise SessionStateError(f"workspace no longer acceptable: {exc}") from None
    if workspace == Path.home().resolve():
        raise SessionStateError("the user's entire home is not an acceptable workspace")

    fields = {f.name for f in dataclasses.fields(SessionConfig)}
    if not isinstance(raw_cfg, dict) or set(raw_cfg) - fields:
        raise SessionStateError("unknown fields in config.json")
    raw_cfg = dict(raw_cfg)
    if raw_cfg.get("state_dir") is not None:
        raw_cfg["state_dir"] = Path(raw_cfg["state_dir"])
    raw_cfg["protected"] = tuple(raw_cfg.get("protected", SessionConfig().protected))
    try:
        cfg = SessionConfig(**raw_cfg)
    except (TypeError, ValueError) as exc:
        raise SessionStateError(f"invalid config: {exc}") from None
    # Never let stored config weaken the mandatory protected set.
    for required in SessionConfig().protected:
        if required not in cfg.protected:
            raise SessionStateError("stored config removes a mandatory protected path")

    layer_root = directory / "layers"
    uppers = []
    if layer_root.exists():
        _check_private_dir(layer_root)
        names = sorted(os.listdir(layer_root))
        if names != [f"{i:03d}" for i in range(len(names))] or not all(_LAYER.match(n) for n in names):
            raise SessionStateError("layer directories are not contiguous")
        for name in names:
            for part in ("upper", "work"):
                info = (layer_root / name / part).lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                    raise SessionStateError(f"layer {name}/{part} is not a real directory")
            uppers.append(layer_root / name / "upper")
    cwds = progress.get("cwds")
    if not isinstance(cwds, list) or len(cwds) != len(uppers):
        raise SessionStateError("recorded steps do not match layers on disk")
    cwds = [_safe_cwd(c) for c in cwds]
    return Session(workspace=workspace, directory=directory, cfg=cfg, uppers=uppers,
                   cwd=cwds[-1] if cwds else ".", closed=False)


@contextlib.contextmanager
def session_lock(directory: Path, wait: bool = True):
    """Serialize run / approve / deny on one session across processes."""
    directory = Path(directory)
    # Never create anything in a directory that is not a private lilguy session.
    _check_private_dir(directory)
    if not (directory / "meta.json").is_file():
        raise SessionStateError(f"{directory} is not a lilguy session")
    fd = os.open(directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            raise SessionBusy("session is in use by another process") from None
        yield
    finally:
        os.close(fd)


def default_state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "state") / "lilguy" / "sessions"


def find_session(ref: str, state_root: Path | None = None) -> Path:
    """Accept a session id (under the state root) or an absolute session path."""
    if ref.startswith("/"):
        return Path(ref)
    if not _ID.match(ref):
        raise SessionStateError(f"not a session id: {ref!r}")
    return (state_root or default_state_root()) / ref
