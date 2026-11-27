"""Application-side understanding of a pending fs.rename request.

Interface v8's fs.rename shows up in a session diff as a plain 'deleted OLD' +
'added NEW' pair per file, like any other change — the sandbox has no notion
of a rename. This module re-derives, from the rule the model proposed and the
rename_target() policy (the single source of truth, from lilguy._typed_step),
which deleted/added pairs are explained by the rename and which are not, so
the human review can say "renamed OLD -> NEW" instead of two unrelated lines.

Nothing here is trusted on its own: a pair is only "confirmed" once the sizes
agree and (when a session is given) the staged bytes of NEW are byte-identical
to the original workspace bytes of OLD. Anything that cannot be confirmed is
reported as unexplained, never silently hidden.
"""
from __future__ import annotations

import dataclasses
from pathlib import PurePosixPath

_CONTENT_CAP = 1 << 20  # bytes compared per pair; bigger files are treated as unconfirmed


def _rename_target_safe(name, rule, width):
    """rename_target(), or None if RULE/WIDTH are missing or invalid for it."""
    from .._typed_step import rename_target
    try:
        return rename_target(name, rule, width)
    except (ValueError, TypeError):
        return None


@dataclasses.dataclass(frozen=True)
class RenamePlan:
    pairs: list  # [(old_path, new_path), ...] sorted by old_path, confirmed only
    unexplained: list  # [(op, path), ...] changes not covered by a confirmed pair


def _args_dict(command: dict) -> dict:
    pairs = command.get("args") or []
    if isinstance(pairs, dict):
        return dict(pairs)
    out = {}
    try:
        for item in pairs:
            key, value = item
            out[key] = value
    except (TypeError, ValueError):
        return {}
    return out


def _bytes_at(path, private_root):
    """Raw bytes at PATH (private read), or None if absent/unreadable/too large."""
    from ..sandbox.private_io import open_private
    if path is None:
        return None
    try:
        with open_private(path, private_root) as stream:
            data = stream.read(_CONTENT_CAP + 1)
    except OSError:
        return None
    if len(data) > _CONTENT_CAP:
        return None
    return data


def _confirm_bytes(session, old_path: str, new_path: str) -> bool:
    from ..sandbox import layers
    try:
        new_staged = layers.resolve(session, new_path)
    except Exception:
        return False
    old_bytes = _bytes_at(session.workspace / old_path, None)
    new_bytes = _bytes_at(new_staged, session.directory)
    if old_bytes is None or new_bytes is None:
        return False
    return old_bytes == new_bytes


def rename_plan(request: dict, session=None) -> RenamePlan | None:
    """None unless REQUEST is an fs.rename request; otherwise the best-effort plan."""
    if not isinstance(request, dict):
        return None
    command = request.get("command")
    if not isinstance(command, dict) or command.get("tool") != "fs.rename":
        return None

    changes = request.get("changes") or []
    if not isinstance(changes, list):
        changes = []

    args = _args_dict(command)
    rule = args.get("rule")
    width = args.get("width")
    # Only the pending step's own changes can be the rename: an earlier step in the same session
    # that happened to delete X and add rule(X) with the same bytes must not be credited to it.
    step_paths = request.get("step_paths")
    in_step = set(step_paths) if isinstance(step_paths, list) else None

    deleted_files = []  # (path, new_name_or_None)
    added_by_path = {}
    other = []  # (op, path) for everything that is not a file delete/add candidate

    for change in changes:
        if not isinstance(change, dict) or "op" not in change or "path" not in change:
            continue
        op, path = change.get("op"), change.get("path")
        kind = change.get("kind")
        if in_step is not None and path not in in_step:
            other.append((op, path))
        elif op == "deleted" and kind == "file":
            parent = PurePosixPath(path).parent
            basename = PurePosixPath(path).name
            new_name = _rename_target_safe(basename, rule, width)
            new_path = str(parent / new_name) if new_name is not None else None
            deleted_files.append((change, new_path))
        elif op == "added" and kind == "file":
            added_by_path[path] = change
        else:
            other.append((op, path))

    pairs = []
    unexplained = list(other)
    for old_change, new_path in deleted_files:
        old_path = old_change["path"]
        new_change = added_by_path.get(new_path) if new_path is not None else None
        confirmed = (
            new_change is not None
            and old_change.get("size_before") == new_change.get("size_after")
            and (session is None or _confirm_bytes(session, old_path, new_path))
        )
        if confirmed:
            pairs.append((old_path, new_path))
        else:
            unexplained.append(("deleted", old_path))

    matched_added = {new for _, new in pairs}
    for path, change in added_by_path.items():
        if path not in matched_added:
            unexplained.append((change.get("op"), path))

    pairs.sort(key=lambda p: p[0])
    unexplained.sort(key=lambda t: t[1])
    return RenamePlan(pairs=pairs, unexplained=unexplained)
