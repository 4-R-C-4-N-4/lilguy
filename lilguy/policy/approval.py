"""Trusted host approval channel. Never register these functions as model tools.

An approval covers exactly the session diff the human saw, bound by a content
hash. Each approved change is also fingerprinted so later steps are not asked
about it again, while any new or altered change is evaluated afresh.
"""
import contextlib
import json
import os
import tempfile
import time

from .commit import (ApprovalMismatch, CommitError, add_approved_fingerprints, diff_hash,
                     entry_fingerprint)

REQUEST = "approval-request.json"
APPROVAL = "approval.json"
NETWORK_REQUEST = "network-request.json"
NETWORK_GRANT = "network-grant.json"


def _defaults(diff_fn, resolve_fn):
    if diff_fn is None:
        from ..sandbox.diff import session_diff
        diff_fn = session_diff
    if resolve_fn is None:
        from ..sandbox.layers import resolve
        resolve_fn = resolve
    return diff_fn, resolve_fn


def load_request(session):
    path = session.directory / REQUEST
    if not path.exists():
        raise CommitError("no pending approval request for this session")
    return json.loads(path.read_text())


@contextlib.contextmanager
def decision_session(directory):
    """Lock a kept session (fail if a step is running), then load and validate it."""
    from ..sandbox import persist
    with persist.session_lock(directory, wait=False):
        yield persist.load_session(directory)


def approve(session, expected_hash, *, diff_fn=None, resolve_fn=None):
    """Bind a trusted human decision to the current immutable session diff."""
    diff_fn, resolve_fn = _defaults(diff_fn, resolve_fn)
    if session.closed:
        raise CommitError("cannot approve a closed session")
    request = load_request(session)
    entries = diff_fn(session)
    current = diff_hash(entries, session, resolve_fn)
    if expected_hash != request["diff_hash"] or current != expected_hash:
        raise ApprovalMismatch(current, expected_hash)
    # Baseline first: a crash before approval.json leaves no authority to run, only fingerprints
    # of changes this human was shown.
    add_approved_fingerprints(session.directory,
                              {entry_fingerprint(e, session, resolve_fn) for e in entries})
    record = {"diff_hash": current, "uid": os.getuid(), "ts": time.time(), "rule": request.get("rule")}
    fd, tmp = tempfile.mkstemp(dir=session.directory, prefix="approval-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, session.directory / APPROVAL)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    from .session import append_audit
    append_audit(session.directory, {"decision": "approval_granted", "diff_hash": current, "uid": os.getuid()})
    return record


def deny(session, *, discard=False, backend=None):
    """Refuse a pending request: roll back the step that asked (or drop the whole session).

    Earlier, already-accepted steps stay. Never touches the real workspace. Callers in a
    separate process must hold the session lock (use decision_session).
    """
    from ..sandbox import layers, persist
    from .session import append_audit
    request = load_request(session)
    if discard:
        append_audit(session.directory, {"decision": "denied", "action": "discard"})
        (backend.discard if backend else layers.discard)(session)
        return [e["path"] for e in request.get("changes", [])]
    if request.get("layers") != len(session.uppers):
        raise CommitError("session changed since the request was made; reopen and review again")
    rolled_back = list(request.get("step_paths", []))
    (backend.rollback_step if backend else layers.rollback_step)(session)
    if (session.directory / "progress.json").exists():
        persist.record_step(session)
        session.cwd = persist.load_session(session.directory).cwd
    for name in (APPROVAL, REQUEST):
        (session.directory / name).unlink(missing_ok=True)
    append_audit(session.directory, {"decision": "denied", "action": "rollback_step",
                                     "rolled_back": rolled_back, "rule": request.get("rule")})
    return rolled_back


# --------------------------------------------------------------------------
# human-readable rendering. Every string from the sandbox is untrusted.
# --------------------------------------------------------------------------

def _clean(text) -> str:
    """Neutralise control characters so command output or file names cannot drive the terminal."""
    out = []
    for ch in str(text):
        code = ord(ch)
        if code < 0x20 or code == 0x7F or 0x80 <= code < 0xA0:
            out.append(f"\\x{code:02x}")
        else:
            out.append(ch)
    return "".join(out)


def _size(n) -> str:
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _describe(change) -> str:
    before, after = change.get("mode_before"), change.get("mode_after")
    parts = []
    if before is not None and after is not None and before != after:
        parts.append(f"mode {before:03o} -> {after:03o}")
    if change["op"] == "deleted":
        parts.append(_size(change.get("size_before")))
    elif change.get("size_after") is not None:
        if change.get("size_before") is not None and change["size_before"] != change["size_after"]:
            parts.append(f"{_size(change['size_before'])} -> {_size(change['size_after'])}")
        else:
            parts.append(_size(change["size_after"]))
    if change.get("symlink_target") is not None:
        parts.append(f"-> {_clean(change['symlink_target'])}")
    if change.get("is_binary"):
        parts.append("binary")
    return ", ".join(p for p in parts if p)


def summarize(session, *, limit: int = 20) -> str:
    request = load_request(session)
    changes = request.get("changes", [])
    new = set(request.get("new_paths", []))
    command = request.get("command", {})
    shown = command.get("tool") or command.get("shell") or " ".join(command.get("argv") or []) or \
        " | ".join(" ".join(stage) for stage in command.get("pipe") or [])
    counts = {}
    for change in changes:
        counts[change["op"]] = counts.get(change["op"], 0) + 1
    lines = [
        f"Session   {_clean(request.get('session_id', session.directory.name))}",
        f"Workspace {_clean(request.get('workspace', session.workspace))}",
        f"Command   {_clean(shown)}   (proposed by the model: untrusted)",
        f"Exit      {request.get('exit_code')}" + (f"   stopped early: {', '.join(request['stopped'])}"
                                                   if request.get("stopped") else ""),
        "",
        f"Needs approval because: {_clean(request.get('rule'))}"
        + (f" ({_clean(request['summary'])})" if request.get("summary") else ""),
        f"Changes in this session: {len(changes)} ("
        + ", ".join(f"{n} {op}" for op, n in sorted(counts.items())) + ")",
        "Nothing reaches your workspace until a separate commit.",
        "",
    ]
    ordered = sorted(changes, key=lambda c: (c["path"] not in new, -(c.get("size_after") or c.get("size_before") or 0),
                                             c["path"]))
    for change in ordered[:limit]:
        marker = "*" if change["path"] in new else " "
        lines.append(f" {marker} {change['op']:<12} {_clean(change['path'])}   {_describe(change)}")
    if len(ordered) > limit:
        lines.append(f"   ... {len(ordered) - limit} more (use --all)")
    if new:
        lines.append("   * = not covered by an earlier approval")
    lines += ["", f"Diff hash {request['diff_hash']}"]
    return "\n".join(lines)


def render_changes(changes, *, limit: int = 20) -> str:
    """Plain listing of a session diff (as dicts), for `lilguy diff` when nothing is pending."""
    if not changes:
        return "No changes in this session."
    ordered = sorted(changes, key=lambda c: c["path"])
    lines = [f"   {c['op']:<12} {_clean(c['path'])}   {_describe(c)}" for c in ordered[:limit]]
    if len(ordered) > limit:
        lines.append(f"   ... {len(ordered) - limit} more (use --all)")
    return "\n".join(lines)



# --- network for one step -------------------------------------------------------------------

def describe_command(spec) -> str:
    import shlex
    if spec.shell is not None:
        return spec.shell
    if spec.argv is not None:
        return shlex.join(spec.argv)
    return " | ".join(shlex.join(stage) for stage in spec.pipe)


def network_request_hash(session, spec) -> str:
    """Binds a network grant to this exact command, cwd and session position (the next step only)."""
    import hashlib
    payload = {"session": session.directory.name, "cwd": session.cwd, "layers": len(session.uppers),
               "shell": spec.shell, "argv": spec.argv, "pipe": spec.pipe}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _write_private_json(path, record) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem + "-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def request_network(session, spec) -> dict:
    record = {"command": describe_command(spec), "cwd": session.cwd, "layers": len(session.uppers),
              "request_hash": network_request_hash(session, spec), "ts": time.time()}
    (session.directory / NETWORK_GRANT).unlink(missing_ok=True)
    _write_private_json(session.directory / NETWORK_REQUEST, record)
    return record


def load_network_request(session) -> dict:
    return json.loads((session.directory / NETWORK_REQUEST).read_text())


def take_network_grant(session, spec) -> bool:
    """True (and the grant is used up) if a human allowed network for exactly this next step."""
    path = session.directory / NETWORK_GRANT
    if not path.exists():
        return False
    grant = json.loads(path.read_text())
    path.unlink()
    return grant.get("request_hash") == network_request_hash(session, spec)


def approve_network(session, expected_hash) -> dict:
    from .session import append_audit
    request = load_network_request(session)
    if expected_hash != request["request_hash"]:
        raise CommitError("the network request differs from the one you reviewed")
    record = {"request_hash": expected_hash, "uid": os.getuid(), "ts": time.time()}
    _write_private_json(session.directory / NETWORK_GRANT, record)
    append_audit(session.directory, {"decision": "network_granted", "command": request["command"],
                                     "request_hash": expected_hash, "uid": os.getuid()})
    return record


def deny_network(session) -> dict:
    from .session import append_audit
    request = load_network_request(session)
    for name in (NETWORK_REQUEST, NETWORK_GRANT):
        (session.directory / name).unlink(missing_ok=True)
    append_audit(session.directory, {"decision": "network_denied", "command": request["command"]})
    return request


def summarize_network(request) -> str:
    return "\n".join([
        "Network requested for one step",
        "",
        f"   command   {_clean(request['command'])}",
        f"   in        {_clean(request['cwd'])}",
        "",
        "If allowed, this one command gets FULL network access, including services listening on",
        "this machine (localhost). Files stay sandboxed and its effects are reviewed afterwards",
        "as usual; local IPC sockets stay blocked.",
        "",
        f"Request hash {request['request_hash']}",
    ])
