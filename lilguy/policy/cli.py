"""Human decisions on a kept sandbox session: `lilguy diff | approve | deny`.

These run in the human's own terminal. They are never exposed to the model:
the session directory is outside the workspace and not mounted in the sandbox.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

LIMIT = 20
STEP_LIMIT = 50


def _parser(prog, help_text):
    parser = argparse.ArgumentParser(prog=f"lilguy {prog}", description=help_text)
    parser.add_argument("session", nargs="?",
                        help="session id or absolute session path (default: the latest session "
                             "with staged changes for the current folder)")
    parser.add_argument("--state-dir", type=Path, help="session state root (default: XDG state dir)")
    parser.add_argument("--all", action="store_true", help="list every changed path")
    return parser


def _open(args):
    from ..sandbox import persist
    from . import approval
    root = args.state_dir.resolve() if args.state_dir else None
    if args.session:
        directory = persist.find_session(args.session, root)
    else:
        directory = latest_session(root or persist.default_state_root(), Path.cwd())
    return approval.decision_session(directory)


def latest_session(state_root: Path, workspace: Path) -> Path:
    """The newest kept session for `workspace` that has staged changes or an open decision.

    Sessions are named `<unix time>-<random>`, so newest first is a numeric sort. Read-only
    (`ask`) sessions and ones with nothing staged are skipped; a session another process is
    using is skipped too, never waited on."""
    import json

    from ..sandbox import diff as sandbox_diff
    from ..sandbox import persist
    from . import approval
    workspace = Path(workspace).resolve()
    state_root = Path(state_root)
    names = [d.name for d in state_root.iterdir() if persist._ID.match(d.name)] if state_root.is_dir() else []
    for name in sorted(names, key=lambda n: (int(n.split("-", 1)[0]), n), reverse=True):
        directory = state_root / name
        try:
            meta = json.loads((directory / "meta.json").read_text())
            if Path(meta.get("workspace", "")).resolve() != workspace:
                continue
            with approval.decision_session(directory) as session:
                if (directory / approval.REQUEST).exists() or sandbox_diff.session_diff(session):
                    return directory
        except (OSError, ValueError, persist.SessionStateError, persist.SessionBusy):
            continue
    raise persist.SessionStateError(f"no session with staged changes for {workspace}; "
                                    "pass a session id, or see `lilguy sessions`")


def _fail(message) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def _print_steps(session, args) -> None:
    """The executed plan comes first, so the human reads what ran before the resulting diff."""
    from . import approval
    print(approval.render_steps(session.directory, limit=None if args.all else STEP_LIMIT))
    print()


def _print_contents(session, entries, args) -> None:
    from . import approval
    big = 10**9
    print(approval.render_contents(session, entries, per_file=big if args.all else 60,
                                   limit=big if args.all else 400))


def _errors():
    from ..sandbox import persist
    from .commit import CommitError
    return (persist.SessionStateError, persist.SessionBusy, CommitError, FileNotFoundError)


def diff_main(argv=None) -> int:
    args = _parser("diff", "Show what a kept session has changed (nothing is committed).").parse_args(argv)
    from ..sandbox import diff as sandbox_diff
    from . import approval
    try:
        with _open(args) as session:
            _print_steps(session, args)
            entries = sandbox_diff.session_diff(session)
            if (session.directory / approval.REQUEST).exists():
                # The summary ends on the diff hash line, which scripts read as the last line.
                _print_contents(session, entries, args)
                print()
                print(approval.summarize(session, limit=10**9 if args.all else LIMIT))
            else:
                changes = [asdict(e) for e in entries]
                print(approval.render_changes(changes, limit=10**9 if args.all else LIMIT))
                if entries:
                    print()
                    _print_contents(session, entries, args)
        return 0
    except _errors() as exc:
        return _fail(exc)


def approve_main(argv=None) -> int:
    parser = _parser("approve", "Approve exactly the pending changes of a kept session.")
    parser.add_argument("--diff-hash", help="approve only if the changes still match this reviewed hash")
    parser.add_argument("--yes", action="store_true", help="skip the prompt (requires --diff-hash)")
    args = parser.parse_args(argv)
    from . import approval
    try:
        with _open(args) as session:
            if _network_only(session):
                return _approve_network(session, args)
            _print_steps(session, args)
            from ..sandbox import diff as sandbox_diff
            _print_contents(session, sandbox_diff.session_diff(session), args)
            print()
            print(approval.summarize(session, limit=10**9 if args.all else LIMIT))
            expected = approval.load_request(session)["diff_hash"]
            if args.diff_hash and args.diff_hash != expected:
                return _fail("the pending changes differ from the hash you reviewed; run `lilguy diff` again")
            if args.yes and not args.diff_hash:
                return _fail("--yes requires --diff-hash, so you approve changes you actually reviewed")
            if not (args.diff_hash and args.yes):
                if not sys.stdin.isatty():
                    if not args.diff_hash:
                        return _fail("refusing to approve without a terminal; pass --diff-hash HASH")
                else:
                    print()
                    print("Approve exactly these changes? They stay in the sandbox until committed. [y/N] ",
                          end="", flush=True)
                    if sys.stdin.readline().strip().lower() not in ("y", "yes"):
                        print("Not approved.")
                        return 1
            approval.approve(session, expected)
        print("Approved. The session can continue; nothing has been written to your workspace.")
        return 0
    except _errors() as exc:
        return _fail(exc)


def deny_main(argv=None) -> int:
    parser = _parser("deny", "Refuse the pending changes: roll back the step that asked.")
    parser.add_argument("--discard", action="store_true", help="drop the whole session instead")
    args = parser.parse_args(argv)
    from . import approval
    try:
        with _open(args) as session:
            if _network_only(session) and not args.discard:
                request = approval.deny_network(session)
                print(f"Network refused for: {approval._clean(request['command'])}. Nothing ran.")
                return 0
            removed = approval.deny(session, discard=args.discard)
        what = "Discarded the session" if args.discard else "Rolled back the last step"
        print(f"{what}. Your workspace was not touched.")
        for path in removed[:LIMIT] if not args.all else removed:
            print(f"   {approval._clean(path)}")
        if len(removed) > LIMIT and not args.all:
            print(f"   ... {len(removed) - LIMIT} more")
        return 0
    except _errors() as exc:
        return _fail(exc)


def _confirm(question: str, diff_hash_arg, expected: str) -> str | None:
    """Returns None when confirmed, else the error/abort message (prefixed 'abort:' for a plain no)."""
    if diff_hash_arg is not None:
        if diff_hash_arg != expected:
            return "the changes differ from the hash you reviewed; run the command again to review"
        return None
    if not sys.stdin.isatty():
        return "refusing without a terminal; pass --diff-hash HASH after reviewing the changes"
    print()
    print(f"{question} [y/N] ", end="", flush=True)
    if sys.stdin.readline().strip().lower() in ("y", "yes"):
        return None
    return "abort:"


def _prepare_commit(session):
    """Recover interrupted commits, then the session's current changes and their hash."""
    import dataclasses

    from ..sandbox import diff as sandbox_diff
    from ..sandbox import layers
    from . import commit as commitmod
    state_dir = Path(session.cfg.state_dir or session.directory.parent)
    session.cfg = dataclasses.replace(session.cfg, state_dir=state_dir)
    recovered = commitmod.recover(session.workspace, state_dir)
    if recovered:
        print(f"Recovered {len(recovered)} interrupted commit(s) first: the workspace was restored "
              f"to how it was before them ({', '.join(recovered)}).")
    commitmod.prune_commits(state_dir)
    entries = sandbox_diff.session_diff(session)
    expected = commitmod.diff_hash(entries, session, layers.resolve) if entries else None
    return state_dir, entries, expected


def _write_commit(session, state_dir, entries, expected):
    """Write exactly the reviewed changes. Returns (commit_id, None) or (None, error)."""
    import shutil

    from ..sandbox import layers
    from . import commit as commitmod
    from .session import append_audit
    try:
        commit_id = commitmod.commit(session, approved_hash=expected)
    except commitmod.ConflictError as exc:
        return None, f"{exc}\nYou changed these files since the session started; nothing was written."
    except commitmod.PolicyRejected as exc:
        return None, f"refused by policy ({exc.args[0].rule if exc.args else 'reject'}); nothing was written"
    except commitmod.ApprovalRequired as exc:
        return None, f"conflict with your workspace: {exc}; nothing was written"
    append_audit(session.directory, {"decision": "committed", "commit_id": commit_id,
                                     "diff_hash": expected, "paths": [e.path for e in entries]})
    audit_dir = state_dir / "audit"
    audit_dir.mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(session.directory / "audit.jsonl", audit_dir / f"{session.directory.name}.jsonl")
    layers.discard(session)
    return commit_id, None


def commit_main(argv=None) -> int:
    parser = _parser("commit", "Write a kept session's changes into the real workspace (journaled, undoable).")
    parser.add_argument("--diff-hash", help="commit only if the changes still match this reviewed hash")
    args = parser.parse_args(argv)
    import dataclasses

    from . import approval
    try:
        with _open(args) as session:
            # approve() only writes approval.json for the exact current diff, and any later step
            # deletes both files, so a request without an approval is an open decision. Committing
            # it is that decision: the reason is shown and the one confirmation covers both.
            pending = (session.directory / approval.REQUEST).exists() and \
                not (session.directory / approval.APPROVAL).exists()
            if pending and _network_only(session):
                return _fail("a network request is pending; answer it with `lilguy approve` or `lilguy deny`")
            state_dir, entries, expected = _prepare_commit(session)
            if not entries:
                print("Nothing to commit.")
                return 0
            _print_steps(session, args)
            print(f"Changes to write into {session.workspace}:")
            print(approval.render_changes([dataclasses.asdict(e) for e in entries],
                                          limit=10**9 if args.all else LIMIT))
            print()
            _print_contents(session, entries, args)
            if pending:
                print()
                print(approval.summarize(session, limit=10**9 if args.all else LIMIT))
            print(f"\nDiff hash {expected}")
            verb = "Approve and write" if pending else "Write"
            problem = _confirm(f"{verb} these {len(entries)} change(s) into {session.workspace}?",
                               args.diff_hash, expected)
            if problem == "abort:":
                print("Not committed. The session is kept.")
                return 1
            if problem:
                return _fail(problem)
            if pending:
                approval.approve(session, approval.load_request(session)["diff_hash"])
            commit_id, error = _write_commit(session, state_dir, entries, expected)
            if error:
                return _fail(error)
        print(f"Committed {len(entries)} change(s) as {commit_id}")
        print(f"Undo with: lilguy undo {commit_id}" + (f" --state-dir {state_dir}" if args.state_dir else ""))
        return 0
    except _errors() as exc:
        return _fail(exc)


def apply_now(session_dir: Path) -> int:
    """`lilguy do`'s single question, asked right after it showed the plan and the diff.

    Only ever called with a terminal on both ends. "y" is the human decision: for a change
    that crossed an approval threshold it approves exactly the shown request and then commits
    it, bound to the same diff hash; anything else leaves the session staged. Network
    requests are never answered here (they need `lilguy approve`)."""
    from . import approval
    try:
        with approval.decision_session(Path(session_dir)) as session:
            if _network_only(session):
                return 0
            pending = (session.directory / approval.REQUEST).exists() and \
                not (session.directory / approval.APPROVAL).exists()
            state_dir, entries, expected = _prepare_commit(session)
            if not entries:
                return 0
            what = "Approve and apply" if pending else "Apply"
            print(f"\n{what} {'this change' if len(entries) == 1 else f'these {len(entries)} changes'} "
                  f"to {session.workspace}? [y/N] ", end="", flush=True)
            if sys.stdin.readline().strip().lower() not in ("y", "yes"):
                print("Not applied; the changes stay staged. Later, from this folder: "
                      "lilguy commit (or lilguy deny).")
                return 1
            if pending:
                approval.approve(session, approval.load_request(session)["diff_hash"])
            commit_id, error = _write_commit(session, state_dir, entries, expected)
            if error:
                return _fail(error)
        print(f"Applied {len(entries)} change(s). Undo with: lilguy undo {commit_id}")
        return 0
    except _errors() as exc:
        return _fail(exc)


def undo_main(argv=None) -> int:
    from ..sandbox import persist
    from . import commit as commitmod
    parser = argparse.ArgumentParser(prog="lilguy undo", description="Reverse a commit (or list undoable ones).")
    parser.add_argument("commit_id", nargs="?", help="omit to list undoable commits, newest first")
    parser.add_argument("--state-dir", type=Path, help="session state root (default: XDG state dir)")
    args = parser.parse_args(argv)
    state_dir = (args.state_dir or persist.default_state_root()).resolve()
    try:
        commits = commitmod.list_commits(state_dir)
        if not args.commit_id:
            if not commits:
                print("No undoable commits (undo data is kept for 7 days).")
            for c in commits:
                import time as _time
                when = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(c["committed_at"]))
                paths = ", ".join(c["paths"][:3]) + (f" +{len(c['paths']) - 3}" if len(c["paths"]) > 3 else "")
                print(f"{c['commit_id']}  {when}  {c['workspace']}  {paths}")
            return 0
        record = next((c for c in commits if c["commit_id"] == args.commit_id), None)
        if record is None:
            return _fail(f"no undoable commit {args.commit_id!r}")
        print(f"Undo {args.commit_id} in {record['workspace']}: restores {len(record['paths'])} path(s)")
        for path in record["paths"][:LIMIT]:
            print(f"   {path}")
        if not sys.stdin.isatty():
            return _fail("refusing to undo without a terminal")
        print("Undo it? [y/N] ", end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            print("Not undone.")
            return 1
        commitmod.undo(Path(record["workspace"]), state_dir, args.commit_id)
        print("Undone.")
        return 0
    except commitmod.CommitError as exc:
        return _fail(exc)


_ACTIVITY_FILES = ("meta.json", "config.json", "progress.json", "audit.jsonl",
                   "approval-request.json", "approval.json")


def _last_activity(directory: Path) -> float:
    times = [(directory / n).stat().st_mtime for n in _ACTIVITY_FILES if (directory / n).is_file()]
    return max(times) if times else directory.stat().st_mtime


def sessions_main(argv=None) -> int:
    import time

    from ..sandbox import layers, persist
    from . import approval
    parser = argparse.ArgumentParser(prog="lilguy sessions",
                                     description="List kept sessions; with --prune, delete idle ones.")
    parser.add_argument("--state-dir", type=Path, help="session state root (default: XDG state dir)")
    parser.add_argument("--prune", type=float, metavar="DAYS",
                        help="delete sessions with no activity for this many days (never your workspace)")
    args = parser.parse_args(argv)
    if args.prune is not None and args.prune < 0:
        return _fail("--prune DAYS must not be negative")
    root = (args.state_dir or persist.default_state_root()).resolve()
    if not root.is_dir():
        print("No kept sessions.")
        return 0
    now = time.time()
    found = 0
    for directory in sorted(root.iterdir()):
        if not persist._ID.match(directory.name) or not (directory / "meta.json").is_file():
            continue  # journals, audit copies, anything else: never touched here
        found += 1
        try:
            idle_days = (now - _last_activity(directory)) / 86400
            with persist.session_lock(directory, wait=False):
                session = persist.load_session(directory)
                waiting = (directory / approval.REQUEST).exists() and not (directory / approval.APPROVAL).exists()
                state = "waiting for approval" if waiting else "approved, not committed" if (
                    directory / approval.APPROVAL).exists() else "kept"
                line = (f"{directory.name}  idle {idle_days:.1f}d  {len(session.uppers)} step(s)  "
                        f"{state}  {approval._clean(str(session.workspace))}")
                if args.prune is not None and idle_days >= args.prune:
                    layers.discard(session)
                    line += "  -> pruned"
                print(line)
        except persist.SessionBusy:
            print(f"{directory.name}  in use by another process, left alone")
        except (persist.SessionStateError, OSError) as exc:
            print(f"{directory.name}  unreadable ({approval._clean(str(exc))}), left alone")
    if not found:
        print("No kept sessions.")
    return 0


def _network_only(session) -> bool:
    """A network request is waiting and no change review is (that one comes first)."""
    from . import approval
    return ((session.directory / approval.NETWORK_REQUEST).exists()
            and not (session.directory / approval.REQUEST).exists())


def _approve_network(session, args) -> int:
    from . import approval
    request = approval.load_network_request(session)
    print(approval.summarize_network(request))
    problem = _confirm("Allow full network for this one command?", args.diff_hash, request["request_hash"])
    if problem == "abort:":
        print("Not allowed. The command will not get network.")
        return 1
    if problem:
        return _fail(problem)
    approval.approve_network(session, request["request_hash"])
    print("Allowed for that one command, as the session's next step.")
    return 0
