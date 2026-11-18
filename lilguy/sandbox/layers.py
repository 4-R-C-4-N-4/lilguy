"""Host-side session/layer-stack management (IMPLEMENTATION.md §5.1, §5.8).

Private per-session state (upper/work dirs, metadata) lives entirely outside
the workspace, under ``cfg.state_dir`` or the XDG state dir default. Nothing
here ever writes into the workspace.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
import time
from pathlib import Path, PurePosixPath

from . import diff
from .backend import Session, SessionConfig


class LayerError(Exception):
    """Raised for session/layer invariant violations."""


def _default_state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "lilguy" / "sessions"


def _state_root(cfg: SessionConfig) -> Path:
    return cfg.state_dir if cfg.state_dir is not None else _default_state_root()


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def _validate_rel(rel: str) -> tuple[str, ...]:
    pure = PurePosixPath(rel)
    if pure.is_absolute():
        raise LayerError(f"rel path must not be absolute: {rel!r}")
    parts = pure.parts
    if any(p == ".." for p in parts):
        raise LayerError(f"rel path must not contain '..': {rel!r}")
    if not parts or parts == (".",):
        raise LayerError("rel path must not be empty")
    return parts


def open_session(workspace: Path, cfg: SessionConfig) -> Session:
    """Create a new session: private state dir outside the workspace, no
    layers yet. Raises LayerError if workspace/state_dir overlap or the
    workspace doesn't exist."""
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise LayerError(f"workspace is not a directory: {workspace}")

    state_root = _state_root(cfg)
    # Always resolve (even if already absolute) so a symlink planted at the
    # configured state_dir can't disguise itself as being outside the
    # workspace while actually pointing straight into it.
    state_root_abs = state_root.resolve()

    if _is_relative_to(state_root_abs, workspace) or _is_relative_to(workspace, state_root_abs):
        raise LayerError(
            f"session state dir ({state_root_abs}) must not be inside or contain the workspace ({workspace})"
        )

    state_root_abs.mkdir(mode=0o700, parents=True, exist_ok=True)
    session_id = f"{int(time.time())}-{secrets.token_hex(8)}"
    directory = state_root_abs / session_id
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(directory, 0o700)

    meta = {
        "workspace": str(workspace),
        "created": time.time(),
        "mount_path": cfg.mount_path,
    }
    (directory / "meta.json").write_text(json.dumps(meta))

    # Automatic per-session snapshot for later conflict detection (owned by
    # lilguy.policy.commit; imported lazily so layers.py has no hard
    # dependency on that module and never writes into the workspace itself,
    # only reads stat facts from it).
    from ..policy import commit as commit_mod
    commit_mod.save_snapshot(directory, commit_mod.capture_snapshot(workspace))

    session = Session(workspace=workspace, directory=directory, cfg=cfg, uppers=[], cwd=".", closed=False)
    from . import persist
    persist.save_config(session)
    return session


def new_layer(s: Session) -> Path:
    """Create the next upper/work layer pair and append the upper to
    ``s.uppers`` (oldest first). Fails closed at ``cfg.max_layers``."""
    if s.closed:
        raise LayerError("session is closed")
    if len(s.uppers) >= s.cfg.max_layers:
        raise LayerError(f"max_layers ({s.cfg.max_layers}) exceeded; squashing is not implemented")

    idx = len(s.uppers)
    layer_root = s.directory / "layers"
    layer_root.mkdir(mode=0o700, exist_ok=True)
    os.chmod(layer_root, 0o700)
    layer_dir = layer_root / f"{idx:03d}"
    upper = layer_dir / "upper"
    work = layer_dir / "work"
    layer_dir.mkdir(mode=0o700, exist_ok=False)
    os.chmod(layer_dir, 0o700)
    upper.mkdir(mode=0o700, exist_ok=False)
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(upper, 0o700)
    os.chmod(work, 0o700)
    s.uppers.append(upper)
    return upper


def _lookup_in_root(parts: tuple[str, ...], root: Path) -> tuple[Path | None, bool]:
    """Resolve ``parts`` under a single layer/workspace root.

    Returns (path, stop) where stop=True means the search must not fall
    through to older layers (whiteout, opaque-ancestor hit, or a
    non-directory ancestor entirely replacing whatever lower layers had
    at this path -- e.g. a symlink standing in for a directory)."""
    cur = root
    hidden = False
    for i, part in enumerate(parts):
        cur = cur / part
        try:
            st = cur.lstat()
        except FileNotFoundError:
            return None, hidden
        except NotADirectoryError:
            return None, hidden
        except PermissionError as exc:
            raise LayerError(f"permission denied statting {cur}") from exc
        is_last = i == len(parts) - 1
        if diff.is_whiteout(cur):
            return None, True
        if is_last:
            return cur, True
        if not stat.S_ISDIR(st.st_mode):
            # a non-directory (file/symlink) sits where an ancestor
            # directory is expected: it entirely replaces whatever used
            # to be at this path in lower layers, so hide them too.
            return None, True
        if diff.is_opaque(cur):
            hidden = True
    return None, hidden


def resolve(s: Session, rel: str, uppers: list[Path] | None = None) -> Path | None:
    """Host-side merged-view resolver (IMPLEMENTATION.md §5.8).

    Searches ``uppers`` (defaults to ``s.uppers``) newest-first, then falls
    back to the workspace. Never follows symlinks while descending ancestors;
    a leaf that is itself a symlink is returned unresolved (for diff/caller
    inspection). Rejects absolute paths and ``..`` components.
    """
    if s.closed:
        raise LayerError("session is closed")
    parts = _validate_rel(rel)

    search_uppers = uppers if uppers is not None else s.uppers
    for layer in reversed(search_uppers):
        found, stop = _lookup_in_root(parts, layer)
        if found is not None:
            return found
        if stop:
            return None

    found, _ = _lookup_in_root(parts, s.workspace)
    return found


def _remove_private_tree(path: Path) -> None:
    """Make only private disposable directories traversable before fd-safe rmtree.

    Never chmod symlinks or anything in the real workspace. File content need
    not be readable to unlink it; only directory owner search/write is restored.
    """
    if not path.exists():
        return
    if path.is_symlink():
        raise LayerError("private session root was replaced by a symlink")
    os.chmod(path, stat.S_IMODE(path.lstat().st_mode) | 0o700)
    def fail(error):
        raise error
    for root, dirs, _ in os.walk(path, followlinks=False, onerror=fail):
        for name in dirs:
            child = Path(root) / name
            info = child.lstat()
            if stat.S_ISDIR(info.st_mode):
                os.chmod(child, stat.S_IMODE(info.st_mode) | 0o700, follow_symlinks=False)
    shutil.rmtree(path)


def rollback_step(s: Session) -> None:
    """Discard the most recent layer (upper+work), as if the step never ran."""
    if s.closed:
        raise LayerError("session is closed")
    if not s.uppers:
        raise LayerError("no layer to roll back")
    top = s.uppers[-1]
    _remove_private_tree(top.parent)
    s.uppers.pop()


def discard(s: Session) -> None:
    """Remove all private session state. Idempotent. Never touches the
    workspace."""
    if s.closed:
        return
    _remove_private_tree(s.directory)
    s.uppers = []
    s.closed = True
