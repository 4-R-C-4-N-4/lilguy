"""Run one command in the sandbox and show its effects; never commits the real workspace.

  lilguy sandbox-run --workspace DIR --cmd '...' [--keep]   start (a kept session can be continued)
  lilguy sandbox-run --session ID --cmd '...'               continue a kept session
"""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .backend import MAX_WALL_S, RunSpec, SessionConfig


class TerminalMonitor:
    """Trusted progress reporting and stall decisions in the human's terminal."""

    def __init__(self, out=None, ask=None):
        self.out = out or sys.stderr
        self.ask = ask if ask is not None else sys.stdin.isatty()

    def _line(self, status):
        from ..policy.approval import _clean
        cpu = f" · CPU {status.cpu_percent:.0f}%" if status.cpu_percent is not None else ""
        last = f" · last output: {_clean(status.last_output_line)[:80]}" if status.last_output_line else ""
        return (f"{int(status.elapsed_s) // 60}m{int(status.elapsed_s) % 60:02d}s{cpu}"
                f" · {status.upper_files} files / {status.upper_bytes // 1024} KB written"
                f" · no progress for {int(status.seconds_since_progress)}s{last}")

    def heartbeat(self, status):
        print(f"[lilguy] still running {self._line(status)}", file=self.out, flush=True)

    def stalled(self, status):
        print(f"[lilguy] looks stuck (busy, no new output or files) {self._line(status)}",
              file=self.out, flush=True)
        if not self.ask:
            print("[lilguy] no terminal to ask; stopping it and keeping its partial work", file=self.out)
            return "stop"
        print("[lilguy] paused. Continue running it? [y/N] ", end="", file=self.out, flush=True)
        answer = sys.stdin.readline().strip().lower()
        return "continue" if answer in ("y", "yes") else "stop"


def _parser():
    parser = argparse.ArgumentParser(prog="lilguy sandbox-run", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--workspace", type=Path)
    where.add_argument("--session", help="continue a kept session (id or absolute path)")
    parser.add_argument("--cmd", required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=600, help="hard wall budget in seconds (default 600)")
    parser.add_argument("--idle-timeout", type=float, default=60,
                        help="stop if nothing happens (no CPU, output or files) for this long")
    parser.add_argument("--stall-timeout", type=float, default=30,
                        help="pause and ask if busy without output or new files for this long")
    parser.add_argument("--mount-path", choices=["real", "short"], default="real")
    parser.add_argument("--network", action="store_true",
                        help="this command needs network (granted per the session's --network-mode)")
    parser.add_argument("--network-mode", choices=["off", "ask", "always"], default="ask",
                        help="new sessions: off, ask (default: you allow full network for one step), always")
    parser.add_argument("--keep", action="store_true", help="keep the session so it can be continued, "
                        "reviewed (lilguy diff), approved or denied")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    from ..policy.session import GuardedSession
    from . import persist
    from .bwrap import BwrapBackend
    backend = BwrapBackend(monitor=TerminalMonitor())
    session = None
    keep = args.keep or args.session is not None
    try:
        if not 0 < args.timeout <= MAX_WALL_S:
            raise ValueError(f"--timeout must be in (0, {MAX_WALL_S}]")
        state_root = args.state_dir.resolve() if args.state_dir else None
        if args.session:
            directory = persist.find_session(args.session, state_root)
            with persist.session_lock(directory, wait=False):
                session = persist.load_session(directory)
            from .runner import _require_capabilities
            from .bwrap import bwrap_path
            _require_capabilities(bwrap_path())
        else:
            cfg = SessionConfig(state_dir=state_root, timeout_s=args.timeout, mount_path=args.mount_path,
                                network=args.network_mode,
                                idle_timeout_s=args.idle_timeout, stall_timeout_s=args.stall_timeout)
            session = backend.open_session(args.workspace, cfg)
        guarded = GuardedSession(backend, session)
        spec = RunSpec(shell=args.cmd, timeout_s=args.timeout if args.session else None, network=args.network)
        outcome = guarded.run(spec)
        print(json.dumps({"session": session.directory.name if keep else None,
                          "session_path": str(session.directory) if keep else None,
                          "committed": False, "retained": keep,
                          "result": asdict(outcome.result), "policy": asdict(outcome.decision)}, indent=2))
        if outcome.decision.kind == "pending":
            if "NETWORK_APPROVAL_REQUIRED" in outcome.result.tags and keep:
                print(f"[lilguy] this command needs network. Allow it once with: lilguy approve "
                      f"{session.directory.name}  — then run the same command again with --session.",
                      file=sys.stderr)
            elif keep:
                print(f"[lilguy] waiting for your decision: lilguy diff {session.directory.name}  |  "
                      f"lilguy approve {session.directory.name}  |  lilguy deny {session.directory.name}",
                      file=sys.stderr)
            else:
                print("[lilguy] needs approval; this preview is discarded. Re-run with --keep to review it.",
                      file=sys.stderr)
            return 2
        return 0 if outcome.result.exit_code == 0 and outcome.decision.kind == "ok" else 1
    except Exception as exc:
        print(f"sandbox failed closed: {exc}", file=sys.stderr)
        return 1
    finally:
        if session is not None and not keep and not session.closed:
            backend.discard(session)
