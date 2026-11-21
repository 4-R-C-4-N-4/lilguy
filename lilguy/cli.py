"""Public commands: probe, eval, and explicitly unsafe v0.1 run.

  python -m lilguy probe
  python -m lilguy run --unsafe-legacy "find the 3 largest files under src" --cwd ~/proj

The legacy runner is NOT sandboxed. Its regex policy is advisory only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import Agent
from .backends import LlamaCpp


def legacy_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("goal")
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-grammar", action="store_true")
    ap.add_argument("--max-steps", type=int, default=15)
    a = ap.parse_args(argv)

    def confirm(cmd: str, why: str) -> bool:
        return input(f"  ? allow [{why}]: {cmd}   [y/N] ").strip().lower() == "y"

    def ask(q: str) -> str | None:
        ans = input(f"  ? model asks: {q}\n  > ").strip()
        return ans or None

    agent = Agent(
        backend=LlamaCpp(a.url, use_grammar=not a.no_grammar, model=a.model),
        root=str(Path(a.cwd).resolve()),
        confirm=confirm, ask=ask, max_steps=a.max_steps, log=print,
    )
    traj = agent.run(a.goal)
    print(f"\n[{traj.final}] {traj.final_arg}  ({len(traj.steps)} steps, {traj.seconds}s)")
    return 0 if traj.final == "done" else 1


def main(argv: list[str] | None = None) -> int:
    """Dispatch phase-local commands; never imply v0.1 execution is sandboxed."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "probe":
        from .probe import main as probe_main
        return probe_main(args[1:])
    if args and args[0] == "eval":
        from .eval import main as eval_main
        return eval_main(args[1:])
    if args and args[0] == "sandbox-run":
        from .sandbox.cli import main as sandbox_main
        return sandbox_main(args[1:])
    if args and args[0] == "do":
        from .do import main as do_main
        return do_main(args[1:])
    if args and args[0] == "ask":
        from . import do
        return do.ask_main(args[1:])
    if args and args[0] in ("approve", "deny", "diff", "commit", "undo", "sessions"):
        from .policy import cli as decision_cli
        return getattr(decision_cli, f"{args[0]}_main")(args[1:])
    if args and args[0] == "run":
        if "--unsafe-legacy" not in args[1:]:
            print("This runs the v0.1 agent on the host. It requires run --unsafe-legacy; "
                  "use sandbox-run for sandboxed commands.", file=sys.stderr)
            return 2
        args.remove("--unsafe-legacy")
        print("WARNING: v0.1 runs commands on the host; regex policy is NOT a sandbox.", file=sys.stderr)
        return legacy_main(args[1:])
    parser = argparse.ArgumentParser(description="lilguy: sandboxed shell for small models")
    parser.add_argument("command", choices=["probe", "sandbox-run", "do", "ask", "diff", "approve", "deny", "commit", "undo", "sessions", "eval", "run"],
                        help="sandbox-run: run a command in the sandbox (preview only); "
                             "do: drive one guarded interface-v1 request with a local model and stage it; "
                             "ask: a question in read-only mode, answered by the model's last command output; "
                             "diff/approve/deny/commit/undo: review a kept session and apply it; probe: host checks; "
                             "eval/run: legacy v0.1 harness (run is NOT sandboxed)")
    parser.parse_args(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
