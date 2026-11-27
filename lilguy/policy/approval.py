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
    from .renames import rename_plan
    plan = rename_plan(request, session)
    if plan is not None:
        lines.append("")
        lines.append("Renames (computed by lilguy from the rule and the staged changes):")
        for old, new_path in plan.pairs:
            lines.append(f"   renamed {_clean(old)} -> {_clean(new_path)}")
        for op, path in plan.unexplained:
            lines.append(f"   ! not part of the rename: {_clean(op)} {_clean(path)}")
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


# --- the executed plan: every step, from the trusted audit log ---------------------------------

_STEP_DECISIONS = {"ok": "ok", "pending": "pending", "reject": "rejected, rolled back"}


def _command_lines(record) -> list[str]:
    args = record.get("args") or {}
    if record.get("tool") != "exec":
        pairs = args.get("args") or []
        pairs = pairs.items() if isinstance(pairs, dict) else pairs
        shown = " ".join(f"{key}={value}" for key, value in pairs)
        return [_clean(f"{args.get('tool', record.get('tool'))} {shown}".rstrip())]
    import shlex
    if args.get("shell") is not None:
        lines = str(args["shell"]).split("\n")
        return [_clean(lines[0])] + [f"> {_clean(line)}" for line in lines[1:]]
    if args.get("argv"):
        return [_clean(shlex.join(args["argv"]))]
    return [_clean(" | ".join(shlex.join(stage) for stage in args.get("pipe") or []))]


def steps_text(records, *, limit: int | None = None, unreadable: int = 0) -> str:
    """Number and render the executed steps in `records` (audit dicts, oldest first).

    Commands come from the sandbox's own audit log, so this shows what ran, not what the model
    claims ran. A pending step is marked approved or denied by later human decisions."""
    steps = []
    for record in records:
        if record.get("tool") and record.get("decision") in _STEP_DECISIONS:
            steps.append({"record": record, "status": _STEP_DECISIONS[record["decision"]]})
        elif record.get("decision") == "approval_granted" and steps and steps[-1]["status"] == "pending":
            steps[-1]["status"] = "pending, approved"
        elif (record.get("decision") == "denied" and record.get("action") == "rollback_step"
              and steps and steps[-1]["status"].startswith("pending")):
            steps[-1]["status"] = "denied, rolled back"
    count = f"{len(steps)} step" + ("" if len(steps) == 1 else "s")
    lines = [f"Executed plan: {count} run in the sandbox (commands proposed by the model, "
             "recorded by lilguy):"]
    shown = steps if limit is None else steps[-limit:]
    if len(shown) < len(steps):
        lines.append(f"   ... {len(steps) - len(shown)} earlier step(s) (use --all)")
    for number, step in enumerate(steps[len(steps) - len(shown):], len(steps) - len(shown) + 1):
        record = step["record"]
        command = _command_lines(record)
        lines.append(f"  {number:>2}. [{step['status']}, exit {record.get('exit')}] $ {command[0]}")
        lines += [f"        {line}" for line in command[1:]]
        changed = [f"{c.get('op')} {_clean(c.get('path'))}" for c in record.get("step_diff") or []]
        if changed:
            label = "attempted" if "rolled back" in step["status"] else "changed"
            lines.append(f"        {label}: " + "; ".join(changed[:10])
                         + (f"; ... {len(changed) - 10} more" if len(changed) > 10 else ""))
    if not steps:
        lines.append("   (no commands were run)")
    if unreadable:
        lines.append(f"   WARNING: {unreadable} audit record(s) unreadable; this history may be incomplete. "
                     "The diff below is still authoritative.")
    return "\n".join(lines)


def render_steps(directory, *, limit: int | None = None) -> str:
    """The executed plan of a session directory, from its private audit.jsonl."""
    path = directory / "audit.jsonl"
    if not path.is_file():
        return "Executed plan: no step history recorded for this session."
    records, unreadable = [], 0
    for line in path.read_text(encoding="utf8", errors="replace").splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            unreadable += 1
    return steps_text(records, limit=limit, unreadable=unreadable)


# --- changed contents: what would reach the workspace, line by line -----------------------------

_CONTENT_CAP = 1 << 20  # bytes read per side; larger files are summarised, not diffed


def _read_side(path, private_root):
    """(text, note): text is None when the side is absent, binary, too large or unreadable."""
    from ..sandbox.private_io import open_private
    if path is None:
        return None, None
    try:
        with open_private(path, private_root) as stream:
            data = stream.read(_CONTENT_CAP + 1)
    except OSError as exc:
        return None, f"contents unavailable ({exc.strerror or exc})"
    if len(data) > _CONTENT_CAP:
        return None, "too large to show"
    if b"\0" in data:
        return None, "binary"
    return data.decode("utf8", errors="replace"), None


def render_contents(session, entries, *, per_file: int = 60, limit: int = 400) -> str:
    """A unified diff of each changed regular text file, workspace side against the session side.

    Shown for review only: the diff hash, not this text, binds what is committed. Every line is
    untrusted and has control characters neutralised."""
    import difflib
    from ..sandbox import layers
    lines, total = ["Changed contents (workspace -> session):"], 0
    for entry in sorted(entries, key=lambda e: e.path):
        if entry.kind != "file" or entry.op == "meta":
            continue
        path = _clean(entry.path)
        if entry.is_binary:
            lines.append(f"   {path}: binary, contents not shown")
            continue
        before_path = session.workspace / entry.path if entry.op != "added" else None
        try:
            after_path = None if entry.op == "deleted" else layers.resolve(session, entry.path)
        except Exception as exc:  # a path the resolver refuses is shown as unavailable, not trusted
            lines.append(f"   {path}: contents unavailable ({_clean(exc)})")
            continue
        before, before_note = _read_side(before_path, None)
        after, after_note = _read_side(after_path, session.directory)
        note = before_note or after_note
        if note:
            lines.append(f"   {path}: {note}")
            continue
        body = list(difflib.unified_diff((before or "").splitlines(), (after or "").splitlines(),
                                         f"a/{path}", f"b/{path}", n=2, lineterm=""))
        if not body:
            continue
        shown = body[:per_file]
        if total + len(shown) > limit:
            lines.append("   ... more changed files not shown (use --all)")
            break
        lines += [f"   {_clean(line)}" for line in shown]
        if len(body) > per_file:
            lines.append(f"   ... {len(body) - per_file} more line(s) in {path}")
        total += len(shown)
    return "\n".join(lines) if len(lines) > 1 else "Changed contents: no text changes to show."



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
