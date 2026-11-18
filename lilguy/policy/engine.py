"""Host-side policy over observed effects, never shell syntax."""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

import yaml

from ..sandbox.backend import DiffEntry


@dataclass(frozen=True)
class Decision:
    kind: str
    rule: str = ""
    detail: str = ""


@dataclass(frozen=True)
class Policy:
    protected: tuple[str, ...] = (".git/**", ".lilguy/**", "**/.env")
    max_deletes: int = 20
    max_modified: int = 50
    max_bytes_written: int = 50_000_000
    delete_free_paths: tuple[str, ...] = ("build/**", "dist/**", "**/__pycache__/**", "**/*.tmp")
    any_delete_outside: tuple[str, ...] | None = ("build/**", "dist/**", "**/*.tmp")
    truncated_to_zero: bool = True
    mode_change: str = "executable_bit"
    symlink_target_outside_root: bool = True
    special_files: bool = True

    def __post_init__(self):
        for value in (self.max_deletes, self.max_modified, self.max_bytes_written):
            if type(value) is not int or value < 0:
                raise ValueError("policy limits must be nonnegative integers")
        if self.mode_change not in ("none", "executable_bit", "any"):
            raise ValueError("invalid mode_change policy")


def matches(path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        variants = [pattern]
        while variants[-1].startswith("**/"):
            variants.append(variants[-1][3:])
        for variant in variants:
            if fnmatchcase(path, variant) or (variant.endswith("/**") and path == variant[:-3]):
                return True
    return False


def _outside(path: str, target: str) -> bool:
    if target.startswith("/"):
        return True
    parts = list(PurePosixPath(path).parent.parts)
    for part in PurePosixPath(target).parts:
        if part == "..":
            if not parts:
                return True
            parts.pop()
        elif part != ".":
            parts.append(part)
    return False


def evaluate(step: list[DiffEntry], session: list[DiffEntry], policy: Policy | None = None,
             *, conflict: bool = False) -> Decision:
    policy = policy or Policy()
    views = (step, session)
    # Reject globally before considering any approval rule in either view.
    for entries in views:
        for entry in entries:
            path = PurePosixPath(entry.path)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                return Decision("reject", "invalid_path", entry.path)
            if matches(entry.path, policy.protected):
                return Decision("reject", "protected", entry.path)
            if entry.kind == "special" and entry.op != "deleted" and policy.special_files:
                return Decision("reject", "special_files", entry.path)
    if conflict:
        return Decision("pending", "conflict", "workspace changed underneath session")
    for entries in views:
        for entry in entries:
            if entry.op == "deleted" and policy.any_delete_outside is not None:
                if not matches(entry.path, policy.any_delete_outside):
                    return Decision("pending", "any_delete_outside", entry.path)
            if (policy.truncated_to_zero and entry.kind == "file" and entry.size_before
                    and entry.size_after == 0 and entry.op in ("modified", "meta")):
                return Decision("pending", "truncated_to_zero", entry.path)
            if entry.mode_before is not None and entry.mode_after is not None:
                changed = entry.mode_before ^ entry.mode_after
                mask = 0o7777 if policy.mode_change == "any" else 0o111 if policy.mode_change == "executable_bit" else 0
                if entry.mode_before & ~entry.mode_after & 0o777:
                    return Decision("pending", "permission_reduction", entry.path)
                if changed & mask:
                    return Decision("pending", "mode_change", entry.path)
            if (policy.symlink_target_outside_root and entry.symlink_target is not None
                    and entry.op != "deleted" and _outside(entry.path, entry.symlink_target)):
                return Decision("pending", "symlink_target_outside_root", entry.path)
        deletes = sum(e.op == "deleted" and not matches(e.path, policy.delete_free_paths) for e in entries)
        modified = sum(e.op in ("modified", "replaced_dir") for e in entries)
        written = sum(e.size_after or 0 for e in entries if e.kind == "file" and e.op in ("added", "modified"))
        for rule, value, limit in (("max_deletes", deletes, policy.max_deletes),
                                   ("max_modified", modified, policy.max_modified),
                                   ("max_bytes_written", written, policy.max_bytes_written)):
            if value > limit:
                return Decision("pending", rule, f"{value} exceeds {limit}")
    return Decision("ok")


def _mapping(value, allowed, context):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f"unknown fields or invalid mapping in {context}")
    return value


def _strings(value):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError("expected a list of nonempty glob strings")
    return tuple(value)


def _bytes(value):
    if type(value) is int:
        return value
    if isinstance(value, str):
        for suffix, multiplier in (("GB", 1_000_000_000), ("MB", 1_000_000), ("KB", 1000)):
            if value.endswith(suffix) and value[:-len(suffix)].isdigit():
                return int(value[:-len(suffix)]) * multiplier
    raise ValueError("invalid byte limit")


def load_policy(path: Path) -> Policy:
    raw = yaml.safe_load(path.read_text())
    raw = _mapping(raw, ("protected", "auto_commit", "require_approval", "reject"), "policy")
    kwargs = {}
    if "protected" in raw:
        kwargs["protected"] = _strings(raw["protected"])
    auto = _mapping(raw.get("auto_commit", {}),
                    ("max_deletes", "max_modified", "max_bytes_written", "delete_free_paths"), "auto_commit")
    for key, value in auto.items():
        kwargs[key] = _strings(value) if key == "delete_free_paths" else _bytes(value) if key == "max_bytes_written" else value
    for section in ("require_approval", "reject"):
        rules = raw.get(section, [])
        if not isinstance(rules, list):
            raise ValueError(f"{section} must be a list")
        for rule in rules:
            allowed = (("any_delete_outside", "truncated_to_zero", "mode_change", "symlink_target_outside_root", "session_conflict")
                       if section == "require_approval" else ("path_matches", "special_files"))
            rule = _mapping(rule, allowed, section)
            if len(rule) != 1:
                raise ValueError("one rule per entry required")
            key, value = next(iter(rule.items()))
            if key == "path_matches":
                if value != "protected":
                    raise ValueError("path_matches must reference protected")
            elif key == "any_delete_outside":
                kwargs[key] = _strings(value)
            elif key == "mode_change":
                kwargs[key] = value
            elif type(value) is not bool:
                raise ValueError(f"{key} must be boolean")
            elif key == "session_conflict":
                if not value:
                    raise ValueError("conflict checking cannot be disabled")
            else:
                kwargs[key] = value
    return Policy(**kwargs)


def evaluate_policies(step: list[DiffEntry], session: list[DiffEntry], policies: list[Policy],
                      *, conflict: bool = False) -> Decision:
    """Intersection of policies: workspace config cannot weaken server config."""
    rank = {"ok": 0, "pending": 1, "reject": 2}
    decisions = [evaluate(step, session, p, conflict=conflict) for p in policies or [Policy()]]
    return max(decisions, key=lambda d: rank[d.kind])


_UNLIMITED = 2**62
# What no configuration can turn off: protected paths, special files, invalid paths, conflicts
# (and permission reduction, decision 001). Approval thresholds are left to trusted config.
MANDATORY = Policy(max_deletes=_UNLIMITED, max_modified=_UNLIMITED, max_bytes_written=_UNLIMITED,
                   delete_free_paths=(), any_delete_outside=None, truncated_to_zero=False,
                   mode_change="none", symlink_target_outside_root=False, special_files=True)


def active_policies(trusted: list[Policy] | None, *, workspace: Policy | None = None) -> list[Policy]:
    """Mandatory floor + trusted (server/caller) policies, or the spec defaults if none given,
    + the workspace's own policy, which can only add restrictions (the strictest decision wins)."""
    out = [MANDATORY, *(trusted or [Policy()])]
    if workspace is not None:
        out.append(workspace)
    return out


def policies_for(workspace_dir, trusted: list[Policy] | None) -> list[Policy]:
    """active_policies() with the workspace's .lilguy/policy.yaml, if it has one."""
    from pathlib import Path
    local = Path(workspace_dir) / ".lilguy" / "policy.yaml"
    workspace = None
    if local.exists():
        local.resolve().relative_to(Path(workspace_dir).resolve())  # no symlink escape
        workspace = load_policy(local)
    return active_policies(trusted, workspace=workspace)
