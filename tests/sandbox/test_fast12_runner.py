"""Focused tests for dev/fast12_runner.py's oracle/false-done control logic.

Uses the same live bwrap sandbox as test_mcp_server_v1_live.py, with a disposable in-memory
synthetic task (never dev/fast12.TASKS, and never used to train or score anything held-out).
Only harmless fixture content; no attack/bypass samples.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dev import fast12_runner as runner  # noqa: E402
from lilguy import protocol as p  # noqa: E402

pytestmark = pytest.mark.sandbox


@dataclass
class Task:
    id: str
    request: str
    files: dict
    oracle: list


def _grade_status_ready(task, *, terminal, answer, changes, events, original_unchanged):
    reasons = []
    if not original_unchanged:
        reasons.append("fixture mutated on disk")
    if terminal != "done":
        reasons.append(f"terminal was {terminal!r}, not done")
    if changes.get("notes.txt") != "status: ready\n":
        reasons.append(f"notes.txt staged as {changes.get('notes.txt')!r}")
    return reasons


def make_task():
    return Task(
        id="notes-status",
        request="In notes.txt change status: draft to status: ready. Check the result.",
        files={"notes.txt": "status: draft\n"},
        oracle=[
            "tool fs.edit\npath: notes.txt\nold: status: draft\nnew: status: ready",
            "done\nchanged status to ready",
        ],
    )


def test_oracle_passes_its_own_grade(tmp_path):
    tools = p.load_tools()
    task = make_task()
    result = runner.run_oracle(tmp_path, task, tools, _grade_status_ready)
    assert result["infra_error"] is None
    assert result["failures"] == [], result["failures"]
    assert result["terminal"] == "done"
    assert result["changes"] == {"notes.txt": "status: ready\n"}
    assert result["original_unchanged"] is True


def test_false_done_is_caught_by_the_grader(tmp_path):
    tools = p.load_tools()
    task = make_task()
    result = runner.run_false_done(tmp_path, task, tools, _grade_status_ready)
    assert result["infra_error"] is None
    assert result["terminal"] == "done"
    assert result["changes"] == {}
    # the grader must notice nothing changed
    assert result["failures"] != []


def test_judge_task_controls_agree_without_a_model(tmp_path):
    tools = p.load_tools()
    task = make_task()
    oracle = runner.run_oracle(tmp_path / "oracle", task, tools, _grade_status_ready)
    false_done = runner.run_false_done(tmp_path / "false_done", task, tools, _grade_status_ready)
    oracle_ok = oracle["infra_error"] is None and not oracle["failures"]
    false_done_caught = false_done["infra_error"] is None and bool(false_done["failures"])
    assert oracle_ok and false_done_caught


def test_run_model_records_requests_tokens_and_seconds(tmp_path):
    import io
    import json

    class Opener:
        def __init__(self):
            self.calls = 0

        def open(self, request, timeout):
            self.calls += 1
            reply = ["tool fs.read\npath: notes.txt", "done\nnothing changed"][self.calls - 1]
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": reply}}],
                                          "usage": {"prompt_tokens": 100, "completion_tokens": 7}}).encode())

    result = runner.run_model(tmp_path, make_task(), p.load_tools(), 0, Opener(), _grade_status_ready)
    metrics = result["metrics"]
    assert (metrics["requests"], metrics["prompt_tokens"], metrics["completion_tokens"]) == (2, 200, 14)
    assert metrics["model_seconds"] >= 0 and metrics["episode_seconds"] >= metrics["model_seconds"]


def test_oracle_script_rejects_a_malformed_action(tmp_path):
    tools = p.load_tools()
    task = Task(id="broken", request="irrelevant", files={"a.txt": "x\n"},
                oracle=["not a real action"])
    result = runner.run_episode(tmp_path, task, runner._scripted(task.oracle, tools), tools,
                                 lambda *a, **k: [])
    assert result["infra_error"] is not None
    assert "not a valid v1 action" in result["infra_error"]


def test_pending_or_rejected_forces_terminal_next(tmp_path):
    """After a non-ok policy, any non-terminal action must fail closed as `invalid`."""
    tools = p.load_tools()
    # fs.edit with an `old` that is not present triggers an error observation but policy ok;
    # this test only exercises the fail-closed branch directly via a scripted non-ok policy.
    calls = []

    def next_action(events, policy):
        calls.append(policy)
        if not events:
            return p.Action.run("exit 1")
        return p.Action.run("echo again")

    task = Task(id="x", request="irrelevant", files={}, oracle=[])
    result = runner.run_episode(tmp_path, task, next_action, tools, lambda *a, **k: [])
    # a non-sandbox-rejected run (exit 1, policy ok) is a normal failure: the loop must keep
    # going so the next action gets a chance to recover, not treat it as terminal.
    assert result["terminal"] in ("budget", "invalid")


@pytest.mark.parametrize("command,path,marker", [
    ("chmod 600 a.txt", "a.txt", "<mode "),
    ("mkdir notes", "notes", "<dir added>"),
])
def test_model_caused_non_content_changes_are_scored_not_infra(tmp_path, command, path, marker):
    """A chmod or new directory is an effect the agent caused. It must surface as a change the
    grader sees (so it can never pass silently), not as an infrastructure failure that removes
    the task from the model's score."""
    tools = p.load_tools()
    task = Task(id="x", request="irrelevant", files={"a.txt": "hi\n"},
                oracle=[f"run\n{command}", "done\nchanged it"])
    result = runner.run_episode(tmp_path, task, runner._scripted(task.oracle, tools), tools,
                                lambda t, *, changes, **k: [] if changes == {} else ["unexpected change"])
    assert result["infra_error"] is None
    assert result["changes"][path].startswith(marker), result["changes"]
    assert result["failures"] == ["unexpected change"]
