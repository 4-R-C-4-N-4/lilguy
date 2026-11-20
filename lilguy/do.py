"""`lilguy do REQUEST`: one v1 trajectory, driven by a loopback llama.cpp model, through
the guarded MCP interface-v1 server only -- staged, never applied, with the diff and the
trusted-human approval handoff on the existing CLI (`lilguy diff|approve|deny|commit`).

Safety posture (why this module exists rather than reusing the legacy agent):

- Preflight, before anything is staged: the sandbox capability probe and the model's own
  reachability are both checked explicitly. Either missing aborts with a clear message.
  There is no fallback to the unsandboxed v0.1 legacy runner, ever.
- `call_tool` here never lets a tool error through on the loop's permissive default: an
  error observation lacking a parseable ``policy:`` line is treated as an infra/protocol
  break and raises, instead of continuing the trajectory under a false "policy: ok".
- The post-run pending/diff handoff is re-derived from the session's own private state
  (approval-request.json, the real session diff) via the same trusted code path `lilguy
  diff`/`approve` use -- never from what the model's observation text claimed. If that
  state cannot be read safely, this reports "unverified" and fails closed, never "clean".
- The record of the run is persisted outside the workspace, under the session's own state
  directory, versioned so a reader can tell which interface/record shape produced it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

from . import loop
from . import protocol as p
from .sandbox import persist

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://127.0.0.1:8080"
RECORD_SCHEMA_VERSION = 1
_SESSION_ID = re.compile(r"^\d+-[0-9a-f]{16}$")
_FORBIDDEN_MODEL_TOOLS = {"approve", "deny", "commit", "apply", "undo"}


class DoSafetyError(RuntimeError):
    """Raised whenever `do` cannot trust the state it is driving, recording or handing off.

    Every caller of this module must treat it as a clean, safe stop: print the reason and
    exit non-zero. It is never retried and never triggers the legacy unsandboxed runner.
    """


# --- preflight: sandbox and model, independently, before anything is staged ----------------

def check_sandbox() -> None:
    """Fail closed if the host cannot run lilguy's sandbox at all."""
    from .probe import run_probe
    failures = [f"{r.name}: {r.detail}" for r in run_probe() if r.required and r.status == "fail"]
    if failures:
        raise DoSafetyError("sandbox is not available: " + "; ".join(failures))


def check_model(url: str, timeout: float = 5.0) -> None:
    """Fail closed if the configured (default: loopback) model server is not reachable."""
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/v1/models", timeout=timeout):
            pass
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DoSafetyError(f"model at {url} is not reachable: {exc}") from None


# --- model-driven next_action: a fresh prompt from `turns` every call, no hidden state -----

def _chat_complete(url: str, model: str | None, messages: list[dict], grammar: str | None,
                    timeout: float) -> str:
    """The network boundary with the model server. Isolated so tests can stub exactly this
    and nothing else, and so a connection failure here is easy to tell apart from a parse
    failure of what it returned."""
    body = {"messages": messages, "temperature": 0.0, "max_tokens": 512}
    if model:
        body["model"] = model
    if grammar:
        body["grammar"] = grammar
    req = urllib.request.Request(
        f"{url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def make_model_driver(tools, request: str, url: str, model: str | None = None,
                       use_grammar: bool = True, timeout: float = 120.0):
    """Build the `next_action` run_loop needs: stateless in `turns` (rebuilt every call, no
    closure state to drift from the Record), using interface v1's own system prompt,
    grammar and canonical action rendering -- the one definition of the protocol, not a
    second one. Network errors and `protocol.ProtocolError` are the only ways this raises;
    the former propagates uncaught by design (loop.py's contract) and is turned into a
    safe abort by the caller, the latter is caught by run_loop itself."""
    system = p.system_prompt(tools)
    grammar = p.grammar(tools) if use_grammar else None

    def next_action(turns, policy):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": f"Request: {request}"}]
        for turn in turns:
            messages.append({"role": "assistant", "content": p.render_action(turn.action, tools)})
            messages.append({"role": "user", "content": p.observation_message(turn.observation)})
        raw = _chat_complete(url, model, messages, grammar, timeout)
        return p.parse_action(raw, tools)

    return next_action


# --- call_tool: the guarded MCP client call, with its own fail-safe on top of run_loop ------

def make_call_tool(client):
    """Wrap one MCP ClientSession as run_loop's `call_tool`.

    Only `run` goes through `{"command": ...}`; every other action is a typed tool call by
    name. An error result with no parseable `policy:` line (a transport/infra failure, a
    crashed tool server, a missing sandbox surfaced mid-run) is never let through on
    policy_of's permissive "ok" default: it is raised here instead, which run_loop does not
    catch, so it aborts the trajectory rather than recording a false success or continuing
    past an unverified state."""
    async def call_tool(action):
        result = await client.call_tool(
            action.tool or "run", action.args if action.tool else {"command": action.text})
        text = result.content[0].text if result.content else ""
        if result.isError and "policy:" not in text:
            raise DoSafetyError(
                "a tool call failed with no parseable policy status; refusing to continue "
                f"without a trustworthy policy outcome: {text!r}")
        return text, result.isError
    return call_tool


# --- record: versioned, private, outside the workspace --------------------------------------

def private_records_dir(state_dir: Path) -> Path:
    directory = Path(state_dir) / "records"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def save_record(state_dir: Path, session_id: str, request: str, workspace: Path,
                 record: "loop.Record") -> Path:
    """Persist the complete, honest trajectory Record privately under `state_dir` (which is
    required to be outside the workspace), versioned by both this record's own schema and
    the interface version it was driven against."""
    directory = private_records_dir(state_dir)
    payload = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "session_id": session_id,
        "workspace": str(workspace),
        "saved_at": time.time(),
        **record.to_jsonable(),
    }
    # Several trajectories can stop before their first tool call: session_id
    # describes the handoff, not the unique identity of such an episode.
    name = f"no-session-{uuid.uuid4().hex}" if session_id == "no-session" else session_id
    path = directory / f"{name}.json"
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{session_id}-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def load_record(path: Path) -> dict:
    """Read back a saved record, refusing one from a schema or interface version this
    reader does not understand rather than guessing at its shape."""
    data = json.loads(Path(path).read_text(encoding="utf8"))
    if data.get("schema_version") != RECORD_SCHEMA_VERSION:
        raise DoSafetyError(f"unsupported record schema_version {data.get('schema_version')!r}")
    if data.get("version") != p.INTERFACE_VERSION:
        raise DoSafetyError(f"record is for interface v{data.get('version')!r}, "
                            f"not v{p.INTERFACE_VERSION}")
    return data


# --- ground-truth session lookup and the human handoff ---------------------------------------

def find_new_session(state_dir: Path) -> Path | None:
    """The sandbox session `lilguy.mcp_server --interface-v1` created under `state_dir`, if
    any -- a trajectory that terminates on `ask` without ever calling a tool opens no
    session at all, which is a legitimate "nothing to hand off" outcome, not a safety
    problem, so zero returns None rather than raising.

    More than one candidate means `state_dir` was reused for more than this run; guessing
    which session is ours is refused.
    """
    state_dir = Path(state_dir)
    if not state_dir.is_dir():
        return None
    candidates = [d for d in state_dir.iterdir()
                  if d.is_dir() and _SESSION_ID.match(d.name) and (d / "meta.json").is_file()]
    if len(candidates) > 1:
        raise DoSafetyError(
            f"expected at most one sandbox session under {state_dir}, found {len(candidates)}; "
            "refusing to guess which one to hand off")
    return candidates[0] if candidates else None


def describe_handoff(session_dir: Path | None) -> str:
    """Re-derive the pending/staged state from the session's own private files -- the same
    ground truth `lilguy diff`/`approve` read -- never from the model's observation text.
    Any failure to read that state safely is reported as unverified, not as clean."""
    if session_dir is None:
        return "Nothing staged; the trajectory never opened a sandbox session. Nothing to review or commit."
    from .policy import approval
    from .sandbox import diff as sandbox_diff
    try:
        with persist.session_lock(session_dir, wait=False):
            session = persist.load_session(session_dir)
            steps = approval.render_steps(session_dir) + "\n\n"
            if (session_dir / approval.REQUEST).exists():
                body = approval.summarize(session)
                contents = approval.render_contents(session, sandbox_diff.session_diff(session))
                return (
                    steps + "A change is staged and WAITING FOR YOUR DECISION; nothing has reached "
                    f"your workspace.\n\n{body}\n\n{contents}\n\n"
                    f"Review:  lilguy diff {session_dir}\n"
                    f"Approve: lilguy approve {session_dir}\n"
                    f"Deny:    lilguy deny {session_dir}"
                )
            entries = sandbox_diff.session_diff(session)
            if not entries:
                return steps + "Nothing staged; the session made no changes. Nothing to review or commit."
            body = approval.render_changes([asdict(e) for e in entries])
            contents = approval.render_contents(session, entries)
            return (
                steps + "Changes are staged (no approval threshold was crossed); nothing has reached "
                f"your workspace.\n\n{body}\n\n{contents}\n\n"
                f"Review: lilguy diff {session_dir}\n"
                f"Commit: lilguy commit {session_dir}"
            )
    except (persist.SessionStateError, persist.SessionBusy, OSError) as exc:
        raise DoSafetyError(
            f"could not verify the staged session's state safely ({exc}); "
            f"inspect it directly before trusting it: lilguy diff {session_dir}") from None


# --- the drive itself: guarded MCP only, never a direct in-process GuardedSession -----------

async def _run(request: str, workspace: Path, state_dir: Path, url: str, model: str | None,
                max_turns: int, use_grammar: bool, timeout: float) -> "loop.Record":
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    tools = p.load_tools()
    env = {k: os.environ[k] for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") if k in os.environ}
    params = StdioServerParameters(command=sys.executable, cwd=str(ROOT), env=env, args=[
        "-m", "lilguy.mcp_server", "--workspace", str(workspace), "--state-dir", str(state_dir),
        "--toolset", str(ROOT / "toolset.yaml"), "--interface-v1",
    ])
    with anyio.fail_after(timeout):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                served = {tool.name for tool in (await client.list_tools()).tools}
                forbidden = served & _FORBIDDEN_MODEL_TOOLS
                if forbidden:
                    raise DoSafetyError(
                        f"the guarded MCP server exposes approval authority to the model: "
                        f"{sorted(forbidden)}; refusing to drive it")
                call_tool = make_call_tool(client)
                next_action = make_model_driver(tools, request, url, model, use_grammar, timeout)
                return await loop.run_loop(call_tool, request, next_action, max_turns)


def drive(request: str, workspace: Path, state_dir: Path, *, url: str = DEFAULT_URL,
          model: str | None = None, max_turns: int = 15, use_grammar: bool = True,
          timeout: float = 300.0, skip_preflight: bool = False) -> tuple["loop.Record", Path | None]:
    """Run one `do` trajectory end to end and return (record, session_dir). `session_dir` is
    None iff the trajectory never opened a sandbox session (e.g. it ended on `ask` without
    any tool call) -- a legitimate outcome, not a failure. Preflight is skippable only for
    tests that stub the model/sandbox boundary themselves; the CLI never skips it."""
    import asyncio
    if not skip_preflight:
        check_sandbox()
        check_model(url)
    record = asyncio.run(_run(request, workspace, state_dir, url, model, max_turns,
                              use_grammar, timeout))
    session_dir = find_new_session(state_dir)
    return record, session_dir


# --- CLI --------------------------------------------------------------------------------------

def _parser():
    parser = argparse.ArgumentParser(
        prog="lilguy do", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("request", help="what you want done, in plain language")
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--state-dir", type=Path, required=True,
                        help="private session state root; must be outside the workspace")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help="loopback llama.cpp server (default: %(default)s)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--no-grammar", action="store_true")
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("--timeout", type=float, default=300.0, help="overall wall budget, seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workspace = args.workspace.resolve()
    state_dir = args.state_dir.resolve()

    try:
        record, session_dir = drive(
            args.request, workspace, state_dir, url=args.url, model=args.model,
            max_turns=args.max_turns, use_grammar=not args.no_grammar, timeout=args.timeout)
    except DoSafetyError as exc:
        print(f"lilguy do failed safely: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # anyio timeouts, transport errors, etc: never a legacy fallback
        print(f"lilguy do failed safely (unexpected error, nothing was applied): {exc}", file=sys.stderr)
        return 2

    try:
        session_id = session_dir.name if session_dir is not None else "no-session"
        record_path = save_record(state_dir, session_id, args.request, workspace, record)
        # The model's own words are a note, not the report: the executed plan and the diff
        # below are rebuilt from the session's trusted state.
        print(f"[{record.terminal}] model's note (unverified): {record.answer or ''}")
        print(f"Record saved: {record_path}")
        print()
        print(describe_handoff(session_dir))
    except (OSError, DoSafetyError) as exc:
        print(f"lilguy do: {exc}", file=sys.stderr)
        return 2
    return 0 if record.terminal in ("done", "ask") else 1


if __name__ == "__main__":
    sys.exit(main())
