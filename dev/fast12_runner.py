"""Oracle vs false-done vs stock-model trial runner over the 12 fast dev tasks.

Three controls per task, each against a fresh fixture and a fresh sandbox session, through the
same guarded interface-v1 MCP server `factory_trial.py` uses:

  oracle:     replay task.oracle (known-good v1 action strings) verbatim, then grade.
  false_done: immediately answer `done` without doing anything, then grade.
  model:      drive the real stock model (via llama-server) through the same loop.

Fail-closed contract: if oracle does not pass its own grade, or false_done *does* pass, the
controls disagree with each other and the task is an infrastructure failure -- the model result
for that task is recorded but never counted as a pass. This is the only way "model miss" (model
really failed the task) is told apart from "infrastructure failure" (the harness/grader itself
is broken for this task), which is why the aggregate records both separately.

No training, no held-out use, no edits outside the disposable per-task fixture/session
directories, and no apply/approve/commit tooling: scoring is read-only, done purely off the
sandbox's own diff of the staged session against the fixture it started from.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from lilguy import protocol as p
from lilguy import loop
from lilguy.sandbox import layers, persist
from lilguy.sandbox.diff import session_diff

MAX_TURNS = 6
# Task oracles are authored in interface-v2 syntax, a superset that accepts done with or without
# text. They are replayed in the interface being evaluated; from v3 a done carries no text.
ORACLE_SYNTAX = 2


class InfraError(RuntimeError):
    """The harness itself could not score a run (not a model miss)."""


# --- fixtures -------------------------------------------------------------------------------

def write_fixture(root: Path, files: dict) -> Path:
    """Materialize task.files (relative path -> text) under root/work, nested dirs included."""
    root.mkdir(parents=True, exist_ok=True)
    ws = root / "work"
    ws.mkdir()
    for rel, text in files.items():
        path = ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf8")
    return ws


def _server_params(ws: Path, state: Path, mode: str = "do",
                   interface: int = p.INTERFACE_VERSION) -> StdioServerParameters:
    env = {k: os.environ[k] for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") if k in os.environ}
    return StdioServerParameters(command=sys.executable, env=env, args=[
        "-m", "lilguy.mcp_server", "--workspace", str(ws), "--state-dir", str(state),
        "--toolset", str(p.TOOLSET), "--interface-v1", "--interface", str(interface),
    ] + (["--read-only"] if mode == "ask" else []))


# --- the shared turn loop ---------------------------------------------------------------------

async def _drive(ws: Path, state: Path, tools, next_action, max_turns: int = MAX_TURNS, mode: str = "do",
                 interface: int = p.INTERFACE_VERSION):
    """Run turns against one guarded MCP session until a terminal action or the budget runs out.

    Thin adapter over the shared `lilguy.loop.run_loop` core: opens the one guarded MCP session,
    wires its `call_tool` to the live client, and projects the resulting `loop.Record` back into
    this module's own (terminal, answer, events) contract so no caller here has to change.
    """
    pending_infra_error = None
    async with stdio_client(_server_params(ws, state, mode, interface)) as (r, w), \
            ClientSession(r, w) as client:
        await client.initialize()

        async def call_tool(action):
            result = await client.call_tool(action.tool or "run",
                                              action.args if action.tool else {"command": action.text})
            return result.content[0].text, result.isError

        try:
            record = await loop.run_loop(call_tool, "", next_action, max_turns)
        except InfraError as exc:
            # Deferred raise: raising inside this anyio TaskGroup wraps the exception in an
            # ExceptionGroup, so we hold it and re-raise plainly once the group has exited.
            pending_infra_error = exc
            record = None
    if pending_infra_error is not None:
        raise pending_infra_error
    events = [(t.action, t.observation, t.is_error) for t in record.turns]
    return record.terminal, record.answer, events


# --- scoring (read-only) ------------------------------------------------------------------------

def _tree(ws: Path) -> dict:
    out = {}
    for path in ws.rglob("*"):
        if path.is_file():
            out[str(path.relative_to(ws))] = path.read_bytes()
    return out


def original_unchanged(ws: Path, files: dict) -> bool:
    """The real fixture on disk must still read exactly as it did before the episode: the
    sandbox backend overlays writes, it never touches the workspace it was opened on."""
    expected = {rel: text.encode("utf8") for rel, text in files.items()}
    return _tree(ws) == expected


def collect_changes(state: Path) -> dict:
    """The net session diff, read-only: path -> staged text, None for a deletion, or a
    `<...>` marker for an effect that is not plain text content (a mode change, a directory,
    a symlink or special file, binary content).

    Every effect the agent caused is reported, so a grader comparing against the expected
    changes sees it as a mismatch and the task cannot pass silently. Only harness-side
    problems raise InfraError: no readable session state, more than one session, or a staged
    path the backend cannot resolve.
    """
    sessions = list(state.glob("*/progress.json"))
    if len(sessions) == 0:
        return {}
    if len(sessions) != 1:
        raise InfraError(f"expected at most one session, found {len(sessions)}")
    session = persist.load_session(sessions[0].parent)
    changes = {}
    for entry in session_diff(session):
        if entry.op == "deleted":
            changes[entry.path] = None
            continue
        if entry.op == "meta":
            changes[entry.path] = f"<mode {entry.mode_before:o}->{entry.mode_after:o}>"
            continue
        if entry.kind != "file":
            changes[entry.path] = f"<{entry.kind} {entry.op}>"
            continue
        target = layers.resolve(session, entry.path)
        if target is None or target.is_symlink() or not target.is_file():
            raise InfraError(f"unexpected staged state for {entry.path}")
        data = target.read_bytes()
        try:
            changes[entry.path] = data.decode("utf8")
        except UnicodeDecodeError:
            changes[entry.path] = f"<binary {len(data)} bytes>"
    return changes


def run_episode(root: Path, task, next_action, tools, grade, mode: str = "do", interface: int = ORACLE_SYNTAX):
    """One fixture + one session + one drive + one read-only scoring pass."""
    ws = write_fixture(root, task.files)
    state = root / "state"
    try:
        terminal, answer, events = asyncio.run(_drive(ws, state, tools, next_action, mode=mode,
                                                      interface=interface))
    except InfraError as exc:
        return {"terminal": "infra-error", "answer": None, "original_unchanged": None,
                "changes": {}, "failures": None, "infra_error": str(exc), "events": []}
    unchanged = original_unchanged(ws, task.files)
    try:
        changes = collect_changes(state)
        infra_error = None
    except InfraError as exc:
        changes, infra_error = {}, str(exc)
    failures = None
    if infra_error is None:
        try:
            failures = list(grade(task, terminal=terminal, answer=answer, changes=changes,
                                   events=events, original_unchanged=unchanged))
        except Exception as exc:  # the grader itself misbehaving is an infra failure too
            infra_error = f"grade() raised: {exc!r}"
    trace_events = [{"action": {"kind": a.kind, "text": a.text, "tool": a.tool, "args": a.args},
                      "observation": text, "is_error": is_error} for a, text, is_error in events]
    return {
        "terminal": terminal, "answer": answer, "original_unchanged": unchanged,
        "changes": changes, "failures": failures, "infra_error": infra_error,
        "events": trace_events,
    }


# --- the three conditions -----------------------------------------------------------------------

def _scripted(lines, tools, version=ORACLE_SYNTAX):
    it = iter(lines)

    def next_action(events, policy):
        try:
            line = next(it)
        except StopIteration:
            return None
        try:
            action = p.parse_action(line, tools, ORACLE_SYNTAX)
        except p.ProtocolError as exc:
            raise InfraError(f"oracle script is not a valid v1 action: {exc}") from exc
        return p.Action.done() if version >= 3 and action.kind == "done" else action

    return next_action


def _false_done(version=ORACLE_SYNTAX):
    done_sent = False

    def next_action(events, policy):
        nonlocal done_sent
        if done_sent:
            return None
        done_sent = True
        return p.Action.done("" if version >= 3 else "done without doing anything (control probe)")

    return next_action


def run_oracle(root: Path, task, tools, grade, version=ORACLE_SYNTAX, mode="do"):
    return run_episode(root, task, _scripted(task.oracle, tools, version), tools, grade, mode, version)


def run_false_done(root: Path, task, tools, grade, version=ORACLE_SYNTAX, mode="do"):
    return run_episode(root, task, _false_done(version), tools, grade, mode, version)


def run_model(root: Path, task, tools, port, opener, grade, version=p.INTERFACE_VERSION, mode="do"):
    ws = write_fixture(root, task.files)
    state = root / "state"
    messages = [{"role": "system", "content": p.system_prompt(tools, version)},
                {"role": "user", "content": p.user_message(task.request, mode, version)}]
    grammar = p.grammar(tools, version)
    metrics = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "model_seconds": 0.0}
    started = time.monotonic()

    async def drive():
        """Thin adapter over `lilguy.loop.run_loop`: builds each llama-server request from the
        shared conversation history and feeds its reply through the same fail-closed core
        `_drive` uses, so the scripted and model paths share one definition of what "done",
        "ask", "budget" and "invalid" mean."""
        async with stdio_client(_server_params(ws, state, mode, version)) as (r, w), \
                ClientSession(r, w) as client:
            await client.initialize()

            async def call_tool(action):
                result = await client.call_tool(action.tool or "run",
                                                  action.args if action.tool else {"command": action.text})
                text, is_error = result.content[0].text, result.isError
                messages.append({"role": "user", "content": p.observation_message(text)})
                return text, is_error

            def next_action(turns, policy):
                body = {"messages": messages, "grammar": grammar, "temperature": 0, "seed": 42,
                        "max_tokens": 256, "chat_template_kwargs": {"enable_thinking": False}}
                req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                              json.dumps(body).encode(), {"Content-Type": "application/json"})
                asked = time.monotonic()
                with opener.open(req, timeout=90) as response:
                    data = json.load(response)
                metrics["model_seconds"] += time.monotonic() - asked
                metrics["requests"] += 1
                usage = data.get("usage") or {}
                metrics["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
                metrics["completion_tokens"] += int(usage.get("completion_tokens", 0))
                reply = data["choices"][0]["message"]["content"]
                messages.append({"role": "assistant", "content": reply})
                try:
                    return p.parse_action(reply, tools, version)
                except p.ProtocolError as exc:
                    messages.append({"role": "user", "content": p.invalid_action_message(str(exc))})
                    raise

            record = await loop.run_loop(call_tool, task.request, next_action, MAX_TURNS, version=version,
                                         mode=mode)
        return (record.terminal, record.answer,
                [(t.action, t.observation, t.is_error) for t in record.turns])

    terminal, answer, events = asyncio.run(drive())
    metrics["episode_seconds"] = time.monotonic() - started
    metrics = {k: round(v, 3) if isinstance(v, float) else v for k, v in metrics.items()}
    unchanged = original_unchanged(ws, task.files)
    try:
        changes = collect_changes(state)
        infra_error = None
    except InfraError as exc:
        changes, infra_error = {}, str(exc)
    failures = None
    if infra_error is None:
        try:
            failures = list(grade(task, terminal=terminal, answer=answer, changes=changes,
                                   events=events, original_unchanged=unchanged))
        except Exception as exc:
            infra_error = f"grade() raised: {exc!r}"
    trace_events = [{"action": {"kind": a.kind, "text": a.text, "tool": a.tool, "args": a.args},
                      "observation": text, "is_error": is_error} for a, text, is_error in events]
    return {
        "terminal": terminal, "answer": answer, "original_unchanged": unchanged,
        "changes": changes, "failures": failures, "infra_error": infra_error,
        "events": trace_events, "metrics": metrics,
    }


# --- per-task verdict ----------------------------------------------------------------------------

_ANSWER_REASON = re.compile(r"^(?:terminal |read-only )?answer\b")


def is_answer_reason(reason: str) -> bool:
    """A failure about the wording of the final done/ask text (as opposed to effects, terminal
    kind, policy or evidence). Every development and held-out grader words these this way."""
    return bool(_ANSWER_REASON.match(reason))


def answer_required(oracle: dict) -> bool:
    """Interface v2 grades the final text only where it is the deliverable: the scripted oracle
    staged nothing and every step stayed `policy: ok` (a question or a no-op report)."""
    return not oracle["changes"] and all(
        loop.policy_of(event["observation"]) == "ok" for event in oracle["events"])


def interface_grade(grade, *, answer_required, version):
    """In v2 the user reviews lilguy's executed plan and diff, so a change task's done text is
    not graded; effects, terminal kind, policy and evidence checks are unchanged. In v3 the
    answer to a question is the quoted output of the last step, so the same answer checks run
    on that quote instead of on the model's words (a v3 done has none)."""
    if version >= 3 and answer_required:
        def quoted(task, *, events, answer, terminal, **kwargs):
            # An `ask` is the one terminal whose own text the user is shown ("what is missing");
            # every other answer is the quote. No development task accepts an ask terminal.
            shown = answer if terminal == "ask" else quote_text(events, task.files)
            return grade(task, events=events, answer=shown, terminal=terminal, **kwargs)
        return quoted
    if version < 2 or answer_required:
        return grade

    def graded(task, **kwargs):
        return [reason for reason in grade(task, **kwargs) if not is_answer_reason(reason)]
    return graded


def quote_text(events, files=None) -> str:
    """The v3 answer: stdout of the last step as lilguy shows it. Empty when there is none, the
    policy refused the step, the command only printed literal text the model typed, or the output
    is just the whole of a multi-line input file (that is the evidence, not an answer)."""
    quote = p.quoted_answer([loop.Turn(action, observation, error) for action, observation, error in events])
    if quote is None or quote.literal:
        return ""
    inputs = {text.rstrip("\n") for text in (files or {}).values() if text.strip().count("\n") >= 1}
    return "" if quote.text.rstrip("\n") in inputs else quote.text


def task_mode(task, version=p.INTERFACE_VERSION, ask_ids=None) -> str:
    """Interface v3 mode an evaluation task is issued in: `ask` for the questions listed in
    `ask_ids` (default: the development questions in dev/oracles_v3.py; the user would type
    `lilguy ask`), `do` for everything else."""
    if version < 3:
        return "do"
    if ask_ids is None:
        from dev.oracles_v3 import ASK as ask_ids
    return "ask" if task.id in ask_ids else "do"


def with_oracle(task, oracle):
    return type(task)(**{**task.__dict__, "oracle": tuple(oracle)})


def _events(run):
    """A recorded run's trace events back as (Action, observation, is_error) tuples."""
    return [(p.Action(**e["action"]), e["observation"], e["is_error"]) for e in run["events"]]


def oracle_for(task, version, oracles=None):
    """v3 replaces the oracle of a question with one whose last command prints the answer."""
    if version >= 3:
        if oracles is None:
            from dev.oracles_v3 import ORACLES as oracles
        if task.id in oracles:
            return with_oracle(task, oracles[task.id])
    return task


def judge_task(root: Path, task, tools, port, opener, grade, version=p.INTERFACE_VERSION, *,
               ask_ids=None, oracles=None) -> dict:
    task = oracle_for(task, version, oracles)
    mode = task_mode(task, version, ask_ids)  # the controls run in the mode the model gets
    oracle = run_oracle(root / "oracle", task, tools, grade, version=version, mode=mode)
    scored = grade if oracle["infra_error"] else interface_grade(
        grade, answer_required=answer_required(oracle), version=version)
    if version >= 3 and oracle["infra_error"] is None:
        failures = list(scored(task, terminal=oracle["terminal"], answer=oracle["answer"],
                               changes=oracle["changes"], events=_events(oracle),
                               original_unchanged=oracle["original_unchanged"]))
        oracle = {**oracle, "failures": failures}
    false_done = run_false_done(root / "false_done", task, tools, scored, version=version, mode=mode)
    model = run_model(root / "model", task, tools, port, opener, scored, version, mode)

    oracle_ok = oracle["infra_error"] is None and not oracle["failures"]
    false_done_caught = false_done["infra_error"] is None and bool(false_done["failures"])
    controls_agree = oracle_ok and false_done_caught

    infra_failure = not controls_agree or model["infra_error"] is not None
    model_ok = model["infra_error"] is None and not model["failures"]
    passed = controls_agree and model_ok and model["infra_error"] is None

    return {
        "task": task.id, "passed": passed, "infra_failure": infra_failure,
        "interface": version, **({"mode": mode} if version >= 3 else {}),
        "model_miss": controls_agree and not model_ok and model["infra_error"] is None,
        "controls_agree": controls_agree,
        "oracle": oracle, "false_done": false_done, "model": model,
    }


# --- managed server lifespan + CLI ---------------------------------------------------------------

@contextlib.contextmanager
def managed_server(server: str, gguf: str, out: Path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with (out / "server.log").open("w") as log:
        proc = subprocess.Popen([server, "-m", gguf, "--host", "127.0.0.1", "--port", str(port),
                                  "-c", "4096", "-np", "1", "-ngl", "all"], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 300
            while proc.poll() is None and time.monotonic() < deadline:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                        if json.load(r).get("status") == "ok":
                            break
                except OSError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("llama-server failed to start; see server.log")
            yield port, opener
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def _load_tasks():
    from dev.fast12 import TASKS, grade  # the other half of this trial; not edited here.
    return list(TASKS), grade


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("server")
    ap.add_argument("gguf")
    ap.add_argument("out", type=Path)
    ap.add_argument("--interface", type=int, default=p.INTERFACE_VERSION, choices=p.SUPPORTED_VERSIONS,
                    help="interface version the model was trained on (prompt, grammar, grading)")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    tasks, grade = _load_tasks()
    tools = p.load_tools()
    verdicts = []
    with managed_server(args.server, args.gguf, args.out) as (port, opener):
        for task in tasks:
            with tempfile.TemporaryDirectory() as tmp:
                verdict = judge_task(Path(tmp), task, tools, port, opener, grade, args.interface)
            verdicts.append(verdict)
            (args.out / f"task_{task.id}.json").write_text(json.dumps(verdict, indent=2) + "\n")

    summary = {
        "total": len(verdicts),
        "passed": sum(1 for v in verdicts if v["passed"]),
        "infra_failures": sum(1 for v in verdicts if v["infra_failure"]),
        "model_misses": sum(1 for v in verdicts if v["model_miss"]),
        "tasks": [{"task": v["task"], "passed": v["passed"], "infra_failure": v["infra_failure"],
                   "model_miss": v["model_miss"], "terminal": v["model"]["terminal"],
                   "metrics": v["model"].get("metrics")} for v in verdicts],
    }
    measured = [v["model"].get("metrics") or {} for v in verdicts]
    summary["model_totals"] = {key: round(sum(m.get(key, 0) for m in measured), 3) for key in
                               ("requests", "prompt_tokens", "completion_tokens", "model_seconds",
                                "episode_seconds")}
    (args.out / "fast12.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(summary)
    return 0 if summary["infra_failures"] == 0 and summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
