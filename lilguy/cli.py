"""Public commands for guarded execution and out-of-band human review."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    """Dispatch guarded commands; the historical host executor is not available."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "probe":
        from .probe import main as probe_main
        return probe_main(args[1:])

    if args and args[0] == "sandbox-run":
        from .sandbox.cli import main as sandbox_main
        return sandbox_main(args[1:])
    if args and args[0] == "do":
        from .do import main as do_main
        return do_main(args[1:])
    if args and args[0] == "ask":
        from . import do
        return do.ask_main(args[1:])
    if args and args[0] in ("setup", "serve", "stop"):
        from . import serve
        return getattr(serve, f"{args[0]}_main")(args[1:])
    if args and args[0] in ("approve", "deny", "diff", "commit", "undo", "sessions"):
        from .policy import cli as decision_cli
        return getattr(decision_cli, f"{args[0]}_main")(args[1:])

    parser = argparse.ArgumentParser(description="lilguy: sandboxed shell for small models")
    parser.add_argument("command", choices=["setup", "serve", "stop", "probe", "sandbox-run", "do", "ask", "diff", "approve", "deny", "commit", "undo", "sessions"],
                        help="setup: point lilguy at its model and GPU; serve/stop: run or stop that model; "
                             "sandbox-run: run a command in the sandbox (preview only); "
                             "do: drive one guarded request with a local model and stage it; "
                             "ask: a question in read-only mode, answered by the model's last command output; "
                             "diff/approve/deny/commit/undo: human review of a kept session; probe: host checks")
    parser.parse_args(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
