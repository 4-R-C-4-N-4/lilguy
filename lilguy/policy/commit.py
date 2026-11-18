"""P2: transactional filesystem commit of a sandbox session's diff onto the
real workspace, with journaled crash recovery and undo.

Ownership boundary: this module does not implement overlay diffing or path
resolution itself (that is lilguy.sandbox.layers / lilguy.sandbox.diff,
owned by other workers and possibly not landed yet). Instead it accepts
``diff_fn`` / ``resolve_fn`` callables with the same signatures as those
future modules and, when not supplied, attempts to import the real ones
lazily so integration is a no-op once they land.

Crash-consistency invariants this module guarantees:
  * The journal records "about to mutate index N" (durably fsync'd) BEFORE
    the filesystem mutation for N happens, and preimages for N (and every
    descendant path that mutation will destroy) are captured before ANY
    mutation in the commit begins. So no matter when the process dies -
    before, during, or immediately after a single _apply_one call - replay
    of the journal always knows exactly which operations must be rolled
    back, and has the data needed to roll them back.
  * Deletions apply deepest-first before type-changing replacements or
    creates, so a directory is never type-replaced while the diff still
    expects children under it to be removed first.
  * A missing conflict-detection snapshot is a hard failure (fail closed),
    never a silent skip.
  * Symlink ancestors in a target path are rejected before any stat/hash/
    preimage work touches that path, so no symlink-escape view of the
    filesystem is ever used to decide what to do.

Public API:
    capture_snapshot(workspace) -> dict
    save_snapshot(dir_, snapshot) -> None
    load_snapshot(dir_) -> dict | None
    diff_hash(entries, session, resolve_fn) -> str
    commit(session, *, approved_hash=None, crash_hook=None,
           diff_fn=None, resolve_fn=None, snapshot=None) -> str
    undo(workspace, state_dir, commit_id) -> None
    recover(workspace, state_dir) -> list[str]
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat as statmod
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Callable

from ..sandbox.backend import DiffEntry, Session
from .engine import Decision, Policy, evaluate_policies


class CommitError(Exception):
    """Base class for commit-time failures."""


class PolicyRejected(CommitError):
    def __init__(self, decision: Decision):
        super().__init__(f"rejected: {decision.rule} {decision.detail}")
        self.decision = decision


class ApprovalRequired(CommitError):
    def __init__(self, decision: Decision, expected_hash: str):
        super().__init__(f"approval required: {decision.rule} {decision.detail}")
        self.decision = decision
        self.expected_hash = expected_hash


class ApprovalMismatch(CommitError):
    def __init__(self, expected_hash: str, got_hash: str | None):
        super().__init__(f"approved_hash does not match current diff ({got_hash!r} != {expected_hash!r})")
        self.expected_hash = expected_hash
        self.got_hash = got_hash


class ConflictError(CommitError):
    """Workspace changed underneath the session since it was opened."""


class UnknownCommit(CommitError):
    pass


class UndoConflict(CommitError):
    """The workspace changed after the commit; undoing would destroy that work."""

    def __init__(self, paths: list[str]):
        self.paths = paths
        shown = ", ".join(paths[:10]) + (f" (+{len(paths) - 10} more)" if len(paths) > 10 else "")
        super().__init__(f"changed since the commit, undo would overwrite: {shown}")


UNDO_RETENTION_S = 7 * 86400

DiffFn = Callable[[Session], "list[DiffEntry]"]
ResolveFn = Callable[[Session, str], "Path | None"]

_COMMIT_ID_RE = re.compile(r"^[0-9]+-[0-9a-f]{12}$")
_CHUNK = 1024 * 1024

# --------------------------------------------------------------------------
# path safety
# --------------------------------------------------------------------------

def _safe_rel(path: str) -> PurePosixPath:
    p = PurePosixPath(path)
    if p.is_absolute() or not p.parts or ".." in p.parts:
        raise CommitError(f"unsafe path: {path!r}")
    return p


def _no_symlink_ancestors(workspace: Path, rel: PurePosixPath) -> None:
    """Reject if any ancestor directory component (not the leaf) is a symlink.

    Must be called before ANY stat/preimage/hash/conflict work touches a
    target path: once an ancestor is a symlink, every subsequent lookup
    under it is attacker-controlled (TOCTOU symlink escape), so nothing
    downstream of this check may be trusted for that path.
    """
    cur = workspace
    for part in rel.parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            raise CommitError(f"symlink ancestor on path: {rel}")


def _validate_target_path(workspace: Path, path: str) -> PurePosixPath:
    """Full gate for a path about to be touched: safety + symlink ancestors."""
    rel = _safe_rel(path)
    _no_symlink_ancestors(workspace, rel)
    return rel


def _is_protected(rel: PurePosixPath, protected: tuple[str, ...]) -> bool:
    from .engine import matches
    return matches(str(rel), protected)


def _validate_state_dir(workspace: Path, state_dir: Path) -> None:
    """Journals/locks must live outside the workspace: a crash-recovery
    journal that sits inside the tree it's protecting can itself be
    clobbered or diffed into the next commit.
    """
    workspace_r = workspace.resolve()
    try:
        state_dir_r = state_dir.resolve()
    except OSError:
        state_dir_r = state_dir
    if state_dir_r == workspace_r or workspace_r in state_dir_r.parents \
            or state_dir_r in workspace_r.parents or state_dir_r == workspace_r:
        raise CommitError("state_dir must not overlap the workspace")


# --------------------------------------------------------------------------
# snapshotting (for conflict detection)
# --------------------------------------------------------------------------

def _entry_stat(path: Path) -> dict | None:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    return {
        "ino": st.st_ino,
        "dev": st.st_dev,
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
        "mode": st.st_mode,
    }


def capture_snapshot(workspace: Path) -> dict:
    """Walk the workspace and record per-path stat facts used later to
    detect whether the real filesystem changed underneath an open session.
    """
    workspace = Path(workspace)
    snap: dict[str, dict] = {}
    for root, dirs, files in os.walk(workspace, followlinks=False):
        rootp = Path(root)
        for name in list(dirs) + files:
            full = rootp / name
            rel = full.relative_to(workspace).as_posix()
            info = _entry_stat(full)
            if info is not None:
                snap[rel] = info
    return snap


def _snapshot_path(dir_: Path) -> Path:
    return Path(dir_) / "commit_snapshot.json"


def save_snapshot(dir_: Path, snapshot: dict) -> None:
    """Persist a conflict-detection snapshot under ``dir_``.

    Callers MUST pass a directory that is unique per session (e.g.
    ``session.directory``), never a dir shared by multiple concurrent
    sessions (e.g. the global ``cfg.state_dir``) - otherwise one session's
    snapshot silently clobbers another's and conflict detection becomes
    meaningless.
    """
    dir_ = Path(dir_)
    dir_.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(dir_, 0o700)
    _atomic_write_json(_snapshot_path(dir_), snapshot)


def load_snapshot(dir_: Path) -> dict | None:
    path = _snapshot_path(Path(dir_))
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _check_conflicts(workspace: Path, entries: list[DiffEntry], snapshot: dict) -> list[str]:
    """Return list of paths that changed on the real workspace since the
    snapshot was taken, for any path this commit intends to touch.
    """
    touched = {entry.path for entry in entries}
    for entry in entries:
        full = workspace / entry.path
        info = _entry_stat(full)
        destructive_tree = (info is not None and statmod.S_ISDIR(info["mode"]) and
                            (entry.op in ("deleted", "replaced_dir") or entry.kind != "dir"))
        if not destructive_tree:
            continue
        prefix = entry.path + "/"
        touched.update(rel for rel in snapshot if rel.startswith(prefix))
        def fail(error):
            raise error
        for root, dirs, files in os.walk(full, followlinks=False, onerror=fail):
            for name in dirs + files:
                touched.add((Path(root) / name).relative_to(workspace).as_posix())
    conflicts = []
    for rel in sorted(touched):
        # Never follow a newly introduced symlink ancestor during conflict checks.
        try:
            _no_symlink_ancestors(workspace, _safe_rel(rel))
        except CommitError:
            conflicts.append(rel)
            continue
        if snapshot.get(rel) != _entry_stat(workspace / rel):
            conflicts.append(rel)
    return conflicts


# --------------------------------------------------------------------------
# hashing / copying for approvals and apply (streamed, never full-buffer)
# --------------------------------------------------------------------------

def _require_regular_source(resolved: Path | None, entry_path: str) -> Path:
    """Fail closed on a missing or non-regular source: a vanished or
    non-file source must never be silently treated as empty content -
    that is a silent data-loss path (writes zero bytes where real content
    was expected).
    """
    if resolved is None:
        raise CommitError(f"missing source content for {entry_path!r}")
    resolved = Path(resolved)
    try:
        st = resolved.lstat()
    except FileNotFoundError:
        raise CommitError(f"source vanished for {entry_path!r}: {resolved}") from None
    if statmod.S_ISLNK(st.st_mode):
        st = resolved.stat()  # follow once; a symlink-to-regular is fine
    if not statmod.S_ISREG(st.st_mode):
        raise CommitError(f"source for {entry_path!r} is not a regular file: {resolved}")
    return resolved


def _stream_hash(path: Path, private_root: Path | None = None) -> str:
    from ..sandbox.private_io import open_private
    h = hashlib.sha256()
    with open_private(path, private_root) as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _stream_copy(src: Path, dst_fileobj, private_root: Path | None = None) -> None:
    from ..sandbox.private_io import open_private
    with open_private(src, private_root) as f:
        while chunk := f.read(_CHUNK):
            dst_fileobj.write(chunk)


def _hash_content(resolve_fn: ResolveFn, session: Session, entry: DiffEntry) -> str:
    if entry.op == "deleted" or entry.kind != "file":
        return ""
    resolved = resolve_fn(session, entry.path)
    resolved = _require_regular_source(resolved, entry.path)
    return _stream_hash(resolved, Path(session.directory))


def diff_hash(entries: list[DiffEntry], session: Session, resolve_fn: ResolveFn) -> str:
    """Canonical sha256 over the diff shape AND resolved file content, so an
    approval cannot be replayed against content that merely matches sizes.
    """
    h = hashlib.sha256()
    for entry in sorted(entries, key=lambda e: e.path):
        content_hash = _hash_content(resolve_fn, session, entry)
        row = (
            entry.op, entry.path, entry.kind, entry.size_before, entry.size_after,
            entry.mode_before, entry.mode_after, entry.symlink_target, entry.is_binary,
            content_hash,
        )
        h.update(json.dumps(row, sort_keys=True, default=str).encode() + b"\n")
    return h.hexdigest()


def entry_fingerprint(entry: DiffEntry, session: Session, resolve_fn: ResolveFn) -> str:
    """Content-bound identity of one change. An approval covers exactly these bytes and metadata."""
    row = (entry.op, entry.path, entry.kind, entry.size_before, entry.size_after,
           entry.mode_before, entry.mode_after, entry.symlink_target, entry.is_binary,
           _hash_content(resolve_fn, session, entry))
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


_BASELINE = "approved-baseline.json"


def load_approved_fingerprints(session_dir: Path) -> set[str]:
    path = Path(session_dir) / _BASELINE
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    if not isinstance(data, list) or not all(isinstance(x, str) and len(x) == 64 for x in data):
        raise CommitError("corrupt approved baseline")
    return set(data)


def add_approved_fingerprints(session_dir: Path, fingerprints: set[str]) -> None:
    merged = load_approved_fingerprints(session_dir) | set(fingerprints)
    _atomic_write_json(Path(session_dir) / _BASELINE, sorted(merged))


def unapproved_entries(entries: list[DiffEntry], session: Session, resolve_fn: ResolveFn,
                       approved: set[str]) -> list[DiffEntry]:
    """Entries a human has not already approved in exactly their current form."""
    if not approved:
        return list(entries)
    return [e for e in entries if entry_fingerprint(e, session, resolve_fn) not in approved]


# --------------------------------------------------------------------------
# lazy resolution of worker-owned modules
# --------------------------------------------------------------------------

def _default_diff_fn() -> DiffFn:
    from ..sandbox import diff as diff_mod  # may not exist yet
    return diff_mod.session_diff


def _default_resolve_fn() -> ResolveFn:
    from ..sandbox import layers as layers_mod  # may not exist yet
    return layers_mod.resolve


# --------------------------------------------------------------------------
# journal (atomic, flock-guarded, fsync'd)
# --------------------------------------------------------------------------

def _lock_path(state_dir: Path, workspace: Path) -> Path:
    key = hashlib.sha256(str(Path(workspace).resolve()).encode()).hexdigest()[:32]
    return Path(state_dir) / f"workspace-{key}.lock"


@contextlib.contextmanager
def _workspace_lock(state_dir: Path, workspace: Path):
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(state_dir, 0o700)
    lock_file = _lock_path(state_dir, workspace)
    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _journal_dir(state_dir: Path) -> Path:
    d = Path(state_dir) / "journal"
    d.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(d, 0o700)
    return d


def _committed_dir(state_dir: Path) -> Path:
    d = Path(state_dir) / "committed"
    d.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(d, 0o700)
    return d


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    _fsync_dir(path.parent)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


# --------------------------------------------------------------------------
# preimages: single path AND full subtree (for destructive type-replacement)
# --------------------------------------------------------------------------

def _preimage(workspace: Path, rel: PurePosixPath) -> dict:
    full = workspace / rel
    try:
        st = full.lstat()
    except FileNotFoundError:
        return {"existed": False}
    if statmod.S_ISLNK(st.st_mode):
        return {"existed": True, "kind": "symlink", "target": os.readlink(full), "mode": st.st_mode}
    if statmod.S_ISDIR(st.st_mode):
        return {"existed": True, "kind": "dir", "mode": st.st_mode}
    if statmod.S_ISREG(st.st_mode):
        return {"existed": True, "kind": "file", "content_b64": _b64(full.read_bytes()), "mode": st.st_mode}
    return {"existed": True, "kind": "special", "mode": st.st_mode}


def _reject_special(workspace: Path, rel: PurePosixPath, pre: dict) -> None:
    """Refuse to touch (including delete) an existing special file: there is
    no safe generic preimage/restore for sockets/fifos/devices, so a commit
    that would clobber one must fail rather than silently lose it.
    """
    if pre.get("existed") and pre.get("kind") == "special":
        raise CommitError(f"refusing to modify special file (no recoverable representation): {rel}")


def _preimage_subtree(workspace: Path, rel: PurePosixPath) -> dict[str, dict]:
    """Preimage ``rel`` and, if it is currently a real (non-symlink) directory,
    every descendant currently on disk under it. This is required before any
    operation that may destroy a whole subtree in one step (e.g. a file or
    symlink replacing a non-empty directory) - without this, rollback only
    knows how to restore the top-level path and every descendant that
    `shutil.rmtree`-style removal destroyed is unrecoverably lost.
    """
    full = workspace / rel
    out: dict[str, dict] = {rel.as_posix(): _preimage(workspace, rel)}
    try:
        is_real_dir = full.is_dir() and not full.is_symlink()
    except OSError:
        is_real_dir = False
    if not is_real_dir:
        return out
    for root, dirs, files in os.walk(full, followlinks=False):
        rootp = Path(root)
        for name in list(dirs) + files:
            dfull = rootp / name
            drel = PurePosixPath(dfull.relative_to(workspace).as_posix())
            out[drel.as_posix()] = _preimage(workspace, drel)
    return out


def _remove_tree_leaf_first(path: Path, keep_root: bool = False) -> None:
    """Remove ``path`` (file, symlink, or directory tree) leaf-first, never
    a single blind `shutil.rmtree` call whose exact deletion set isn't
    guaranteed to match what was preimaged.
    """
    if path.is_symlink() or not path.is_dir():
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
        return
    for root, dirs, files in os.walk(path, topdown=False, followlinks=False):
        rootp = Path(root)
        for name in files:
            with contextlib.suppress(FileNotFoundError):
                os.remove(rootp / name)
        for name in dirs:
            d = rootp / name
            if d.is_symlink():
                with contextlib.suppress(FileNotFoundError):
                    os.remove(d)
            else:
                with contextlib.suppress(FileNotFoundError, OSError):
                    os.rmdir(d)
    if not keep_root:
        with contextlib.suppress(FileNotFoundError, OSError):
            os.rmdir(path)


def _order_for_apply(entries: list[DiffEntry]) -> list[DiffEntry]:
    """Ordering that is safe for destructive type changes:

      1. deletions, deepest path first (children removed before parents)
      2. type-changing replacements (e.g. dir -> file), shallow first
      3. everything else (added/modified/meta/trashed), shallow first

    Deletions must run before replacements because a diff that replaces a
    directory ``d`` with a file while also deleting ``d/child`` is only
    safe to apply if ``d/child`` is removed while ``d`` is still a
    directory; doing the type replacement first destroys ``d/child``
    without it ever being accounted for as its own deletion.
    """
    def key(e: DiffEntry):
        depth = len(PurePosixPath(e.path).parts)
        if e.op == "deleted":
            return (0, -depth)
        if e.op == "replaced_dir":
            return (1, depth)
        return (2, depth)
    return sorted(entries, key=key)


def _apply_one(workspace: Path, entry: DiffEntry, resolve_fn: ResolveFn | None,
                session: Session | None) -> None:
    rel = _safe_rel(entry.path)
    _no_symlink_ancestors(workspace, rel)
    full = workspace / rel
    full.parent.mkdir(parents=True, exist_ok=True)

    if entry.op == "deleted":
        if full.is_symlink() or full.is_file():
            os.remove(full)
        elif full.is_dir():
            os.rmdir(full)
        return

    if entry.kind == "dir":
        if full.is_symlink() or (full.exists() and not full.is_dir()):
            os.remove(full)
        full.mkdir(parents=True, exist_ok=True)
        if entry.mode_after is not None:
            os.chmod(full, statmod.S_IMODE(entry.mode_after))
        return

    if entry.kind == "symlink":
        target = entry.symlink_target
        if target is None:
            raise CommitError(f"symlink entry without target: {entry.path}")
        if full.is_dir() and not full.is_symlink():
            _remove_tree_leaf_first(full)
        fd_name = f".{rel.name}.{uuid.uuid4().hex}.tmp"
        tmp = full.parent / fd_name
        os.symlink(target, tmp)
        try:
            os.replace(tmp, full)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.remove(tmp)
            raise
        return

    if entry.kind == "file":
        if full.is_dir() and not full.is_symlink():
            _remove_tree_leaf_first(full)
        resolved = resolve_fn(session, entry.path) if resolve_fn else None
        source = _require_regular_source(resolved, entry.path)
        fd, tmp_name = tempfile.mkstemp(dir=full.parent, prefix=f".{rel.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                _stream_copy(source, f, Path(session.directory) if session is not None else None)
                f.flush()
                os.fsync(f.fileno())
            mode = statmod.S_IMODE(entry.mode_after) if entry.mode_after is not None else 0o644
            os.chmod(tmp_name, mode)
            os.replace(tmp_name, full)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
            raise
        _fsync_dir(full.parent)
        return

    raise CommitError(f"cannot apply entry kind={entry.kind!r} op={entry.op!r}")


def _restore_preimage(workspace: Path, rel: PurePosixPath, pre: dict) -> None:
    full = workspace / rel
    if not pre.get("existed"):
        if full.is_symlink() or full.is_file():
            with contextlib.suppress(FileNotFoundError):
                os.remove(full)
        elif full.is_dir():
            with contextlib.suppress(OSError):
                os.rmdir(full)
        return
    kind = pre["kind"]
    full.parent.mkdir(parents=True, exist_ok=True)
    if kind == "dir":
        if full.is_symlink() or (full.exists() and not full.is_dir()):
            os.remove(full)
        full.mkdir(parents=True, exist_ok=True)
        os.chmod(full, statmod.S_IMODE(pre["mode"]))
    elif kind == "symlink":
        if full.is_dir() and not full.is_symlink():
            _remove_tree_leaf_first(full)
        tmp = full.parent / f".{rel.name}.{uuid.uuid4().hex}.restore.tmp"
        os.symlink(pre["target"], tmp)
        os.replace(tmp, full)
    elif kind == "file":
        if full.is_dir() and not full.is_symlink():
            _remove_tree_leaf_first(full)
        fd, tmp_name = tempfile.mkstemp(dir=full.parent, prefix=f".{rel.name}.", suffix=".restore.tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(_unb64(pre["content_b64"]))
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp_name, statmod.S_IMODE(pre["mode"]))
            os.replace(tmp_name, full)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
            raise
    else:
        pass  # special files: no safe generic restore; leave as-is.


def _restore_subtree(workspace: Path, rel: PurePosixPath, preimages: dict[str, dict]) -> None:
    """Restore ``rel`` to its preimaged state, including any descendants
    that were preimaged alongside it. New descendants left behind by a
    (now being undone) mutation are removed first, then the path itself is
    restored (parent before children), then any preimaged descendants are
    restored shallowest-first so parent directories exist before the files
    that go inside them.
    """
    full = workspace / rel
    try:
        now_is_dir = full.is_dir() and not full.is_symlink()
    except OSError:
        now_is_dir = False
    if now_is_dir:
        _remove_tree_leaf_first(full, keep_root=True)

    rel_key = rel.as_posix()
    _restore_preimage(workspace, rel, preimages.get(rel_key, {"existed": False}))

    prefix = rel_key + "/"
    descendant_keys = sorted(
        (k for k in preimages if k.startswith(prefix)),
        key=lambda k: k.count("/"),
    )
    for k in descendant_keys:
        _restore_preimage(workspace, PurePosixPath(k), preimages[k])


def _serialize_entries(entries: list[DiffEntry]) -> list[dict]:
    return [vars(e) for e in entries]


def _deserialize_entries(rows: list[dict]) -> list[DiffEntry]:
    return [DiffEntry(**row) for row in rows]


# --------------------------------------------------------------------------
# public: commit
# --------------------------------------------------------------------------

def commit(session: Session, *, approved_hash: str | None = None,
           crash_hook=None, diff_fn: DiffFn | None = None,
           resolve_fn: ResolveFn | None = None, snapshot: dict | None = None,
           policies: list[Policy] | None = None) -> str:
    """Journal and apply ``session``'s diff onto the real workspace.

    ``crash_hook(index, entry)`` is called right before applying the entry
    at ``index``; tests use it to kill -9 the process mid-commit.

    ``snapshot``, when not supplied explicitly, is loaded from
    ``session.directory`` (never from the shared ``cfg.state_dir``, which
    is common across concurrent sessions). If no snapshot can be found at
    all, conflict detection fails CLOSED: every touched path is treated as
    conflicting rather than silently skipping the check.
    """
    workspace = Path(session.workspace)
    state_dir = session.cfg.state_dir
    if state_dir is None:
        raise CommitError("session.cfg.state_dir is required to journal commits")
    state_dir = Path(state_dir)
    _validate_state_dir(workspace, state_dir)

    diff_fn = diff_fn or _default_diff_fn()
    resolve_fn = resolve_fn or _default_resolve_fn()
    entries = list(diff_fn(session))

    # Full target-path gate (safety + symlink ancestors) before any other
    # work (stats, preimages, hashing, conflict checks) touches these paths.
    rels = {}
    for entry in entries:
        rels[entry.path] = _validate_target_path(workspace, entry.path)

    if snapshot is None:
        snapshot = load_snapshot(Path(session.directory))

    with _workspace_lock(state_dir, workspace):
        if snapshot is None:
            # Fail closed: we have no record of the pre-session state, so
            # we cannot rule out an external mutation. Treat every touched
            # path as conflicting rather than silently skipping the check.
            conflicts = [e.path for e in entries]
        else:
            conflicts = _check_conflicts(workspace, entries, snapshot)

        # Mandatory floor (protected paths, special files, conflicts) that no config can lift,
        # + trusted policies (spec defaults if none) + the workspace policy, which only tightens.
        from .engine import policies_for
        active_policies = policies_for(workspace, policies)
        decision = evaluate_policies(entries, entries, active_policies, conflict=bool(conflicts))
        if decision.kind != "reject" and not conflicts:
            # Changes a human already approved, in exactly their current form, do not need
            # approving again. Conflicts and rejections are never excused by a baseline.
            residual = unapproved_entries(entries, session, resolve_fn,
                                          load_approved_fingerprints(Path(session.directory)))
            decision = evaluate_policies(residual, residual, active_policies)
        if decision.kind == "reject":
            raise PolicyRejected(decision)
        if decision.kind == "pending":
            expected = diff_hash(entries, session, resolve_fn)
            if approved_hash is None:
                raise ApprovalRequired(decision, expected)
            if approved_hash != expected:
                raise ApprovalMismatch(expected, approved_hash)
            if conflicts:  # never overwrite a human edit, whatever rule was reported
                raise ConflictError(f"workspace changed: {conflicts}")

        # Refuse to touch existing special files (sockets/fifos/devices):
        # there is no safe generic preimage/restore for them.
        for entry in entries:
            rel = rels[entry.path]
            _reject_special(workspace, rel, _preimage(workspace, rel))

        commit_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:12]}"
        ordered = _order_for_apply(entries)

        # Preimage every path AND every descendant any entry's destructive
        # removal would destroy, all captured before any mutation starts so
        # the snapshot is of pristine pre-commit state.
        preimages: dict[str, dict] = {}
        for e in ordered:
            preimages.update(_preimage_subtree(workspace, rels[e.path]))

        journal = {
            "commit_id": commit_id,
            "workspace": str(workspace),
            "status": "pending",
            "applied_index": -1,
            "entries": _serialize_entries(ordered),
            "preimages": preimages,
        }
        jpath = _journal_dir(state_dir) / f"{commit_id}.json"
        _atomic_write_json(jpath, journal)

        try:
            for index, entry in enumerate(ordered):
                if crash_hook is not None:
                    crash_hook(index, entry)
                # Durable intent BEFORE the mutation: record (and fsync) that
                # we are about to touch index `index` first, so a crash
                # during or immediately after the mutation itself still
                # leaves the journal pointing at an index whose preimage is
                # known and will be rolled back.
                journal["applied_index"] = index
                _atomic_write_json(jpath, journal)
                _apply_one(workspace, entry, resolve_fn, session)
        except BaseException:
            _rollback_journal(workspace, journal)
            journal["status"] = "rolled_back"
            _atomic_write_json(jpath, journal)
            raise

        journal["status"] = "committed"
        journal["committed_at"] = time.time()
        # What the workspace looks like right after this commit, so undo can refuse to
        # overwrite anything the human changes later.
        journal["postimage"] = _postimage(workspace, sorted({rels[e.path] for e in ordered}))
        _atomic_write_json(jpath, journal)
        cpath = _committed_dir(state_dir) / f"{commit_id}.json"
        _atomic_write_json(cpath, journal)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(jpath)

    if snapshot is not None:
        new_snapshot = dict(snapshot)
        for entry in entries:
            if entry.op == "deleted":
                new_snapshot.pop(entry.path, None)
            else:
                info = _entry_stat(workspace / entry.path)
                if info is not None:
                    new_snapshot[entry.path] = info
        save_snapshot(Path(session.directory), new_snapshot)

    return commit_id


def _rollback_journal(workspace: Path, journal: dict) -> None:
    applied_index = journal["applied_index"]
    entries = _deserialize_entries(journal["entries"])
    preimages = journal["preimages"]
    for index in range(applied_index, -1, -1):
        rel = _safe_rel(entries[index].path)
        _restore_subtree(workspace, rel, preimages)


# --------------------------------------------------------------------------
# public: recover (post crash)
# --------------------------------------------------------------------------

def recover(workspace: Path, state_dir: Path) -> list[str]:
    """Scan incomplete journals for ``workspace`` and roll each back to its
    pre-commit state. Returns the commit_ids that were recovered.
    """
    workspace = Path(workspace)
    state_dir = Path(state_dir)
    recovered = []
    with _workspace_lock(state_dir, workspace):
        jdir = _journal_dir(state_dir)
        for jpath in sorted(jdir.glob("*.json")):
            journal = json.loads(jpath.read_text())
            if journal.get("workspace") != str(workspace):
                continue
            if journal.get("status") == "pending":
                _rollback_journal(workspace, journal)
                journal["status"] = "rolled_back"
                _atomic_write_json(jpath, journal)
                recovered.append(journal["commit_id"])
            with contextlib.suppress(FileNotFoundError):
                os.unlink(jpath)
    return recovered


# --------------------------------------------------------------------------
# public: undo (reverse a previously completed commit)
# --------------------------------------------------------------------------

def _state_of(path: Path) -> dict | None:
    """Content-level state of one path, never following symlinks."""
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    mode = statmod.S_IMODE(st.st_mode)
    if statmod.S_ISLNK(st.st_mode):
        return {"kind": "symlink", "target": os.readlink(path)}
    if statmod.S_ISDIR(st.st_mode):
        return {"kind": "dir", "mode": mode}
    if statmod.S_ISREG(st.st_mode):
        try:
            digest = _stream_hash(path)
        except PermissionError:
            digest = f"unreadable:{st.st_size}:{st.st_mtime_ns}:{st.st_ino}"
        return {"kind": "file", "mode": mode, "sha256": digest}
    return {"kind": "special", "mode": mode, "ino": st.st_ino}


def _postimage(workspace: Path, rels) -> dict[str, dict | None]:
    """State of every committed path and everything beneath it, right after the commit."""
    out: dict[str, dict | None] = {}
    for rel in rels:
        full = workspace / rel
        out[str(rel)] = _state_of(full)
        if out[str(rel)] and out[str(rel)]["kind"] == "dir":
            for root, dirs, files in os.walk(full):  # os.walk does not follow symlinks by default
                for name in dirs + files:
                    child = Path(root) / name
                    out[str(child.relative_to(workspace))] = _state_of(child)
    return out


def _changed_since(workspace: Path, post: dict[str, dict | None]) -> list[str]:
    tops = [p for p in post if not any(p.startswith(o + "/") for o in post if o != p)]
    now = _postimage(workspace, [PurePosixPath(p) for p in tops])
    return sorted(p for p in set(post) | set(now) if post.get(p) != now.get(p))


def list_commits(state_dir: Path) -> list[dict]:
    """Undoable commits, newest first: {commit_id, workspace, committed_at, paths}."""
    out = []
    for cpath in _committed_dir(Path(state_dir)).glob("*.json"):
        if not _COMMIT_ID_RE.match(cpath.stem):
            continue
        try:
            journal = json.loads(cpath.read_text())
        except (OSError, ValueError):
            continue
        out.append({"commit_id": journal.get("commit_id", cpath.stem), "workspace": journal.get("workspace"),
                    "committed_at": journal.get("committed_at", int(cpath.stem.split("-")[0]) / 1000),
                    "paths": [e["path"] for e in journal.get("entries", [])]})
    return sorted(out, key=lambda c: (c["committed_at"], c["commit_id"]), reverse=True)


def prune_commits(state_dir: Path, retention_s: float = UNDO_RETENTION_S) -> list[str]:
    """Delete undo data older than the retention window. Returns the pruned commit ids."""
    cutoff = time.time() - retention_s
    pruned = []
    for record in list_commits(state_dir):
        if record["committed_at"] < cutoff:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(_committed_dir(Path(state_dir)) / f"{record['commit_id']}.json")
            pruned.append(record["commit_id"])
    return pruned


def undo(workspace: Path, state_dir: Path, commit_id: str) -> None:
    """Restore the workspace to before ``commit_id``; refuses if anything changed since."""
    if not _COMMIT_ID_RE.match(commit_id):
        raise UnknownCommit(f"malformed commit_id: {commit_id!r}")
    workspace = Path(workspace)
    state_dir = Path(state_dir)
    cpath = _committed_dir(state_dir) / f"{commit_id}.json"
    if not cpath.exists():
        raise UnknownCommit(commit_id)
    journal = json.loads(cpath.read_text())
    if journal.get("workspace") != str(workspace):
        raise UnknownCommit(f"{commit_id} belongs to a different workspace")
    with _workspace_lock(state_dir, workspace):
        if "postimage" not in journal:
            raise UndoConflict(["(commit recorded without post-commit state; refusing to guess)"])
        changed = _changed_since(workspace, journal["postimage"])
        if changed:
            raise UndoConflict(changed)
        _rollback_journal(workspace, journal)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(cpath)
