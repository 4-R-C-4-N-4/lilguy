"""Walk overlay upper layers and produce DiffEntry lists.

See IMPLEMENTATION.md §5.7. Whiteouts (char device 0:0) and the
``user.overlay.opaque`` xattr only exist inside a real overlay mount
produced in a user namespace; unit tests exercise this module by
monkeypatching :func:`is_whiteout` / :func:`is_opaque` directly
(documented in IMPLEMENTATION.md §5.7 as acceptable for unit tests).
"""
from __future__ import annotations

import hashlib
import os
import stat
from contextvars import ContextVar
from pathlib import Path

from .backend import DiffEntry, Session
from .private_io import open_private

OPAQUE_XATTR = "user.overlay.opaque"
_HASH_CHUNK = 1 << 16
_BINARY_SNIFF_BYTES = 8192
# Private session directory of the diff in progress: files there may be read even if a
# sandboxed command removed read permission. Workspace files are never widened.
_PRIVATE_ROOT: ContextVar[Path | None] = ContextVar("lilguy_private_root", default=None)


class DiffError(Exception):
    """Raised when the diff walk cannot safely determine the truth (e.g. a
    permission-denied directory/file). We fail closed rather than silently
    returning an incomplete/empty diff."""


def is_whiteout(path: Path) -> bool:
    """True if ``path`` is an overlay whiteout (char device, major/minor 0:0)."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        return False
    except NotADirectoryError:
        return False
    except PermissionError as exc:
        raise DiffError(f"permission denied statting {path}") from exc
    if not stat.S_ISCHR(st.st_mode):
        return False
    rdev = st.st_rdev
    return os.major(rdev) == 0 and os.minor(rdev) == 0


def is_opaque(path: Path) -> bool:
    """True if ``path`` (a directory) carries ``user.overlay.opaque = y``."""
    try:
        value = os.getxattr(str(path), OPAQUE_XATTR, follow_symlinks=False)
    except OSError:
        return False
    return value == b"y"


def _kind_of(st: os.stat_result) -> str:
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "special"


def _hash_file(path: Path) -> bytes:
    h = hashlib.sha256()
    try:
        with open_private(path, _PRIVATE_ROOT.get()) as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
                h.update(chunk)
    except PermissionError as exc:
        raise DiffError(f"cannot read {path}") from exc
    return h.digest()


def _is_binary(path: Path) -> bool:
    try:
        with open_private(path, _PRIVATE_ROOT.get()) as f:
            chunk = f.read(_BINARY_SNIFF_BYTES)
    except PermissionError as exc:
        raise DiffError(f"cannot read {path}") from exc
    except OSError:
        return False
    return b"\x00" in chunk


def _symlink_target(path: Path) -> str | None:
    try:
        return os.readlink(path)
    except OSError:
        return None


def _lstat_or_raise(path: Path) -> os.stat_result | None:
    """lstat ``path``; return None if it simply doesn't exist, but fail
    closed (raise) on permission errors instead of pretending it's absent."""
    try:
        return path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except PermissionError as exc:
        raise DiffError(f"permission denied statting {path}") from exc


def _scandir_or_raise(d: Path) -> list[os.DirEntry] | None:
    """scandir ``d``; return None if it doesn't exist / isn't a directory,
    but fail closed (raise) on permission errors."""
    try:
        return list(os.scandir(d))
    except (FileNotFoundError, NotADirectoryError):
        return None
    except PermissionError as exc:
        raise DiffError(f"permission denied reading directory {d}") from exc


def _lookup(parts: tuple[str, ...], roots: list[Path]) -> tuple[Path | None, os.stat_result | None]:
    """Resolve ``parts`` against ``roots`` (newest-first), honoring ancestor
    whiteouts/opaque dirs and tombstones at the leaf. Never follows symlinks
    while descending ancestors."""
    for root in roots:
        cur = root
        hidden_here = False
        ok = True
        for i, part in enumerate(parts):
            cur = cur / part
            st = _lstat_or_raise(cur)
            if st is None:
                ok = False
                break
            is_last = i == len(parts) - 1
            if is_whiteout(cur):
                return None, None  # tombstoned in the newest layer that has it: fully hidden
            if is_last:
                return cur, st
            if not stat.S_ISDIR(st.st_mode):
                ok = False
                break
            if is_opaque(cur):
                hidden_here = True
        if ok:
            continue
        if hidden_here:
            return None, None
    return None, None


def _lower_lookup(rel_parts: tuple[str, ...], lower_layers: list[Path], workspace: Path):
    roots = list(lower_layers) + [workspace]
    return _lookup(rel_parts, roots)


def _merged_listing(rel: str, lower_layers: list[Path], workspace: Path) -> dict[str, tuple[Path, os.stat_result]]:
    """Merged directory listing of ``rel`` across lower layers + workspace,
    honoring whiteouts (tombstones hide the name from all older layers)."""
    seen: set[str] = set()
    out: dict[str, tuple[Path, os.stat_result]] = {}
    roots = list(lower_layers) + [workspace]
    for root in roots:
        d = root
        hidden = False
        missing = False
        for part in rel.split("/") if rel else ():
            d = d / part
            st = _lstat_or_raise(d)
            if st is None:
                missing = True
                break
            if is_whiteout(d) or not stat.S_ISDIR(st.st_mode):
                return out
            hidden = hidden or is_opaque(d)
        if missing:
            if hidden:
                break
            continue
        entries = _scandir_or_raise(d)
        if entries is None:
            if hidden:
                break
            continue
        for e in entries:
            if e.name in seen:
                continue
            seen.add(e.name)
            p = Path(e.path)
            st = _lstat_or_raise(p)
            if st is None:
                continue
            if is_whiteout(p):
                continue
            out[e.name] = (p, st)
        if hidden or is_opaque(d):
            break
    return out


def _emit_deleted_tree(rel: str, lower_path: Path, lower_st: os.stat_result, out: list[DiffEntry],
                        lower_layers: list[Path], workspace: Path) -> None:
    if stat.S_ISDIR(lower_st.st_mode):
        out.append(DiffEntry(op="deleted", path=rel, kind="dir",
                              size_before=lower_st.st_size, mode_before=stat.S_IMODE(lower_st.st_mode)))
        for name, (p, st) in sorted(_merged_listing(rel, lower_layers, workspace).items()):
            child_rel = f"{rel}/{name}"
            _emit_deleted_tree(child_rel, p, st, out, lower_layers, workspace)
    else:
        kind = _kind_of(lower_st)
        entry = DiffEntry(op="deleted", path=rel, kind=kind,
                           size_before=lower_st.st_size if kind == "file" else None,
                           mode_before=stat.S_IMODE(lower_st.st_mode),
                           symlink_target=_symlink_target(lower_path) if kind == "symlink" else None)
        out.append(entry)


def _diff_leaf(rel: str, upper_path: Path, st: os.stat_result,
                lower_path: Path | None, lower_st: os.stat_result | None) -> DiffEntry | None:
    """Compare a non-directory upper entry against its (optional) lower
    counterpart. Caller guarantees ``lower_st`` is either None or the same
    *kind* as ``st`` (type changes are handled by the caller as a
    delete+add pair so we never hash through a symlink or diff a file
    against a directory)."""
    kind = _kind_of(st)
    if lower_st is None:
        entry = DiffEntry(op="added", path=rel, kind=kind,
                           size_after=st.st_size if kind == "file" else None,
                           mode_after=stat.S_IMODE(st.st_mode))
        if kind == "symlink":
            entry.symlink_target = _symlink_target(upper_path)
        elif kind == "file":
            entry.is_binary = _is_binary(upper_path)
        return entry

    mode_before = stat.S_IMODE(lower_st.st_mode)
    mode_after = stat.S_IMODE(st.st_mode)

    if kind == "symlink":
        target_before = _symlink_target(lower_path)
        target_after = _symlink_target(upper_path)
        if target_before == target_after and mode_before == mode_after:
            return None
        return DiffEntry(op="modified", path=rel, kind=kind,
                          mode_before=mode_before, mode_after=mode_after,
                          symlink_target=target_after)

    if kind == "file":
        size_before = lower_st.st_size
        size_after = st.st_size
        if size_before != size_after:
            return DiffEntry(op="modified", path=rel, kind=kind,
                              size_before=size_before, size_after=size_after,
                              mode_before=mode_before, mode_after=mode_after,
                              is_binary=_is_binary(upper_path))
        same_content = _hash_file(lower_path) == _hash_file(upper_path)
        if same_content:
            if mode_before == mode_after:
                return None
            return DiffEntry(op="meta", path=rel, kind=kind,
                              size_before=size_before, size_after=size_after,
                              mode_before=mode_before, mode_after=mode_after,
                              is_binary=_is_binary(upper_path))
        return DiffEntry(op="modified", path=rel, kind=kind,
                          size_before=size_before, size_after=size_after,
                          mode_before=mode_before, mode_after=mode_after,
                          is_binary=_is_binary(upper_path))

    # special files: compare mode only (no content concept)
    if mode_before == mode_after:
        return None
    return DiffEntry(op="meta", path=rel, kind=kind, mode_before=mode_before, mode_after=mode_after)


def _emit_leaf_change(rel: str, upath: Path, st: os.stat_result,
                       lower_path: Path | None, lower_st: os.stat_result | None,
                       out: list[DiffEntry], lower_layers: list[Path], workspace: Path) -> None:
    """Diff a single non-directory upper entry against the lower view,
    handling type changes (e.g. a file replacing a symlink, or a plain
    leaf replacing an entire lower directory tree) as delete+add so
    _diff_leaf never has to compare mismatched kinds or follow a
    symlink's target when hashing."""
    if lower_st is not None and _kind_of(lower_st) != _kind_of(st):
        _emit_deleted_tree(rel, lower_path, lower_st, out, lower_layers, workspace)
        entry = _diff_leaf(rel, upath, st, None, None)
        if entry is not None:
            out.append(entry)
        return
    entry = _diff_leaf(rel, upath, st, lower_path, lower_st)
    if entry is not None:
        out.append(entry)


def _walk_level(rel_prefix: str, stack: list[Path], base_layers: list[Path], out: list[DiffEntry],
                inherited_opaque: bool = False) -> None:
    """Diff the union of ``stack`` (upper roots, newest-first, representing
    "changes") against ``base_layers`` (newest-first "before" roots) at
    directory ``rel_prefix``.

    Used both for a single step (``stack=[upper]``, ``base_layers`` = older
    uppers + workspace) and for a whole session (``stack`` = all uppers
    newest-first, ``base_layers=[workspace]``) so the net diff is derived
    from one real merged-view computation rather than folding independent
    step diffs together.
    """
    sources: dict[str, tuple[Path, os.stat_result, bool]] = {}
    for root in stack:
        # `root` is always already positioned at the directory corresponding
        # to `rel_prefix` (the initial call passes the real upper root with
        # rel_prefix=""; recursive calls pass pre-joined child directories),
        # so it is never re-joined with rel_prefix here.
        d = root
        entries = _scandir_or_raise(d)
        if entries is None:
            continue
        for e in entries:
            if e.name in sources:
                continue
            p = Path(e.path)
            st = _lstat_or_raise(p)
            if st is None:
                continue
            sources[e.name] = (p, st, is_whiteout(p))
        if is_opaque(d):
            break

    for name, (upath, st, wh) in sorted(sources.items()):
        child_rel = f"{rel_prefix}/{name}" if rel_prefix else name
        parts = tuple(child_rel.split("/"))
        lower_path, lower_st = _lookup(parts, base_layers)

        if wh:
            if lower_st is not None:
                _emit_deleted_tree(child_rel, lower_path, lower_st, out, base_layers[:-1], base_layers[-1])
            continue

        if stat.S_ISDIR(st.st_mode):
            child_stack: list[Path] = []
            for root in stack:
                cand = root / name
                cst = _lstat_or_raise(cand)
                if cst is None:
                    if is_opaque(root):
                        break
                    continue
                if not stat.S_ISDIR(cst.st_mode):
                    break
                child_stack.append(cand)
                if is_opaque(cand) or is_opaque(root):
                    break
            is_opaque_here = is_opaque(upath) or inherited_opaque or any(is_opaque(root) for root in stack)
            lower_is_dir = lower_st is not None and stat.S_ISDIR(lower_st.st_mode)
            if is_opaque_here and lower_is_dir:
                mb, ma = stat.S_IMODE(lower_st.st_mode), stat.S_IMODE(st.st_mode)
                out.append(DiffEntry(op="replaced_dir", path=child_rel, kind="dir",
                                      mode_before=mb, mode_after=ma))
            elif lower_st is None or not lower_is_dir:
                out.append(DiffEntry(op="added", path=child_rel, kind="dir",
                                      mode_after=stat.S_IMODE(st.st_mode)))
                if lower_st is not None:
                    # a plain file/symlink/special used to live here; its
                    # whole prior identity (and any descendants, if it was
                    # somehow a dir-that-doesn't-look-dir-anymore) is gone
                    _emit_deleted_tree(child_rel, lower_path, lower_st, out, base_layers[:-1], base_layers[-1])
            else:
                mb, ma = stat.S_IMODE(lower_st.st_mode), stat.S_IMODE(st.st_mode)
                if mb != ma:
                    out.append(DiffEntry(op="meta", path=child_rel, kind="dir",
                                          mode_before=mb, mode_after=ma))

            if is_opaque_here and lower_is_dir:
                upper_names = {e.name for root in child_stack for e in (_scandir_or_raise(root) or [])}
                hidden = _merged_listing(child_rel, base_layers[:-1], base_layers[-1])
                for nm, (p, lst) in sorted(hidden.items()):
                    if nm in upper_names:
                        continue
                    _emit_deleted_tree(f"{child_rel}/{nm}", p, lst, out, base_layers[:-1], base_layers[-1])

            # build the next level's upper stack: every root in `stack` that
            # also has a (non-opaque-shadowed) directory at this name,
            # newest-first, stopping right after the first opaque one.
            _walk_level(child_rel, child_stack, base_layers, out, inherited_opaque=is_opaque_here)
            continue

        _emit_leaf_change(child_rel, upath, st, lower_path, lower_st, out, base_layers[:-1], base_layers[-1])


def step_diff(s: Session, upper: Path) -> list[DiffEntry]:
    """Diff a single step's ``upper`` against the merged view of the layers
    beneath it (older uppers, oldest first, then the workspace)."""
    idx = s.uppers.index(upper)
    lower_layers = list(reversed(s.uppers[:idx]))  # newest-first for lookup
    out: list[DiffEntry] = []
    token = _PRIVATE_ROOT.set(s.directory)
    try:
        _walk_level("", [upper], lower_layers + [s.workspace], out)
    finally:
        _PRIVATE_ROOT.reset(token)
    out.sort(key=lambda e: e.path)
    return out


def session_diff(s: Session) -> list[DiffEntry]:
    """Compute the net effect of every layer against the workspace directly
    (one merged-view walk), not by folding independent step diffs: a value
    changed and then reverted must cancel exactly, and intermediate
    metadata-only steps must not leak into the final shape."""
    stack = list(reversed(s.uppers))  # newest-first
    out: list[DiffEntry] = []
    token = _PRIVATE_ROOT.set(s.directory)
    try:
        _walk_level("", stack, [s.workspace], out)
    finally:
        _PRIVATE_ROOT.reset(token)
    return sorted(out, key=lambda e: e.path)
