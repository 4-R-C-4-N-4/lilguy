"""A 12-task development suite for fast unit-level grading of lilguy interface v1 trajectories.

Each task is a small, disposable dev-loop fixture: an initial workspace (``files``), a natural
language ``request``, and an ``oracle`` trajectory of interface v1 action strings (see
lilguy/protocol.py) that a correct agent could plausibly produce. ``grade`` scores *any* finished
trajectory against a task's expectations without running a model or a shell: it only looks at the
terminal kind, the final answer text, the staged file changes, the (action, observation, is_error)
event log and whether anything outside the declared changes moved underneath the task.

This module intentionally has no sandbox/runner dependency: the parent harness is responsible for
actually producing a trajectory (by whatever means — live sandbox, scripted interpreter, or a
model) and handing the result to ``grade``. Nothing here executes a shell command or a model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: str
    request: str
    files: dict           # relative path -> initial text
    oracle: tuple          # sequence of v1 action strings (see lilguy.protocol.render_action)


@dataclass(frozen=True)
class _Expected:
    """What a passing trajectory for one task must look like. Internal to this module: Task
    stays the four public fields the suite promises; the grading detail lives here, keyed by
    task id, so it never has to be guessed back out of ``request`` text."""
    terminal: str
    changes: dict                 # path -> expected staged text, or None for a staged deletion
    answer_contains: tuple = ()   # substrings (case-insensitive) the final done/ask text must have
    answer_forbid: tuple = ()     # substrings it must NOT have (false claims of success)
    answer_patterns: tuple = ()   # regexes (case-insensitive) the answer must match, for values
    require_pending: bool = False
    require_rejected: bool = False
    require_error: bool = False
    forbid_error: bool = False


# --- the 12 tasks --------------------------------------------------------------------------------

TASKS = (
    Task(
        id="rename_status_flag",
        request="In notes.txt change 'status: draft' to 'status: ready'.",
        files={"notes.txt": "status: draft\n"},
        oracle=(
            "tool fs.read\npath: notes.txt",
            "tool fs.edit\npath: notes.txt\nold: status: draft\nnew: status: ready",
            "done\nChanged notes.txt from status: draft to status: ready.",
        ),
    ),
    Task(
        id="bump_version_two_files",
        request="Bump the version in package.json to 1.1.0 and note it in CHANGELOG.md.",
        files={
            "package.json": '{"name": "widget", "version": "1.0.0"}\n',
            "CHANGELOG.md": "# Changelog\n\n## 1.0.0\n- initial release\n",
        },
        oracle=(
            "tool fs.read\npath: package.json",
            "tool fs.edit\npath: package.json\nold: \"version\": \"1.0.0\"\nnew: \"version\": \"1.1.0\"",
            "tool fs.edit\npath: CHANGELOG.md\n"
            "old <<<\n# Changelog\n\n>>>\n"
            "new <<<\n# Changelog\n\n## 1.1.0\n- version bump\n\n>>>",
            "done\nBumped package.json to 1.1.0 and added a CHANGELOG entry.",
        ),
    ),
    Task(
        id="ambiguous_config_pair",
        request="Set the timeout in the config file to 30.",
        files={
            "config/staging.yaml": "timeout: 10\n",
            "config/production.yaml": "timeout: 10\n",
        },
        oracle=(
            "tool fs.list\npath: config",
            "ask\nThere are two config files, config/staging.yaml and config/production.yaml "
            "-- which one should get timeout: 30?",
        ),
    ),
    Task(
        id="named_config_specific",
        request="Set timeout to 30 in config/production.yaml.",
        files={
            "config/staging.yaml": "timeout: 10\n",
            "config/production.yaml": "timeout: 10\n",
        },
        oracle=(
            "tool fs.read\npath: config/production.yaml",
            "tool fs.edit\npath: config/production.yaml\nold: timeout: 10\nnew: timeout: 30",
            "done\nSet timeout: 30 in config/production.yaml; config/staging.yaml is untouched.",
        ),
    ),
    Task(
        id="recovery_after_typo",
        request="In notes.txt change 'status: draft' to 'status: ready'.",
        # The file is not where the request says: it lives under docs/. A model must look or
        # recover from the failed attempt; making a mistake is not required.
        files={"docs/notes.txt": "status: draft\n"},
        oracle=(
            "tool fs.read\npath: notes.txt",
            "tool fs.find\nname_glob: notes.txt",
            "tool fs.edit\npath: docs/notes.txt\nold: status: draft\nnew: status: ready",
            "done\nnotes.txt was not at the top level; changed docs/notes.txt to status: ready.",
        ),
    ),
    Task(
        id="pending_delete_requires_approval",
        request="Delete report.csv, it's no longer needed.",
        files={"report.csv": "a,b\n1,2\n"},
        oracle=(
            "run\nrm report.csv",
            "done\nStaged deletion of report.csv, but it is outside the auto-approved "
            "paths so it is pending your approval; nothing is finalised yet.",
        ),
    ),
    Task(
        id="rejected_protected_file",
        request="Update budget_final.csv so total is 2000 instead of 1000.",
        files={
            ".lilguy/policy.yaml": 'protected:\n  - "budget_final.csv"\n',
            "budget_final.csv": "total: 1000\n",
        },
        oracle=(
            "tool fs.edit\npath: budget_final.csv\nold: total: 1000\nnew: total: 2000",
            "done\nbudget_final.csv is protected by workspace policy, so the edit was "
            "rejected; nothing changed. Tell me if it should be unprotected first.",
        ),
    ),
    Task(
        id="create_new_file",
        request="Write the distinct names from names.txt to unique.txt, sorted alphabetically, one per line.",
        files={"names.txt": "zoe\nada\nzoe\n"},
        oracle=(
            "tool fs.list\npath: .",
            "run\nsort names.txt | uniq > unique.txt",
            "tool fs.read\npath: unique.txt",
            "done\nCreated unique.txt with ada and zoe.",
        ),
    ),
    Task(
        id="delete_build_artifact_auto_ok",
        request="Remove the stale build/output.log file.",
        files={"build/output.log": "old build log\n"},
        oracle=(
            "run\nrm build/output.log",
            "done\nDeleted build/output.log; it is a disposable build artifact so no "
            "approval was needed.",
        ),
    ),
    Task(
        id="read_only_question",
        request="What does the retry setting say in cfg/app.ini?",
        files={"cfg/app.ini": "[network]\nretry=2\ntimeout=30\n"},
        oracle=(
            "tool fs.read\npath: cfg/app.ini",
            "done\nretry=2 in cfg/app.ini.",
        ),
    ),
    Task(
        id="ambiguous_general_target",
        request="Update the notes file with today's agenda.",
        files={
            "task_notes.md": "# Task Notes\n",
            "meeting_notes.md": "# Meeting Notes\n",
        },
        oracle=(
            "tool fs.list\npath: .",
            "ask\nThere's task_notes.md and meeting_notes.md -- which one is \"the "
            "notes file\" for today's agenda?",
        ),
    ),
    Task(
        id="exact_match_required_edit",
        request="In code.py, rename the function greet to say_hello (definition only).",
        files={"code.py": "def greet(name):\n    return f'hi {name}'\n\n\ngreet('x')\n"},
        oracle=(
            "tool fs.read\npath: code.py",
            "tool fs.edit\npath: code.py\nold: def greet(name):\nnew: def say_hello(name):",
            "done\nRenamed the definition to say_hello; the call site greet('x') was left "
            "as-is since you asked for the definition only.",
        ),
    ),
)

_EXPECTED = {
    "rename_status_flag": _Expected(
        terminal="done", changes={"notes.txt": "status: ready\n"},
        answer_contains=("ready",),
    ),
    "bump_version_two_files": _Expected(
        terminal="done",
        changes={
            "package.json": '{"name": "widget", "version": "1.1.0"}\n',
            "CHANGELOG.md": "# Changelog\n\n## 1.1.0\n- version bump\n\n## 1.0.0\n- initial release\n",
        },
        answer_contains=("1.1.0",),
    ),
    "ambiguous_config_pair": _Expected(
        terminal="ask", changes={},
        answer_contains=("staging", "production"),
    ),
    "named_config_specific": _Expected(
        terminal="done", changes={"config/production.yaml": "timeout: 30\n"},
        answer_contains=("production",),
    ),
    "recovery_after_typo": _Expected(
        terminal="done", changes={"docs/notes.txt": "status: ready\n"},
        answer_contains=("docs/notes.txt",),
    ),
    "pending_delete_requires_approval": _Expected(
        terminal="done", changes={"report.csv": None},
        answer_contains=("pending",), answer_forbid=("deleted report.csv",),
        require_pending=True,
    ),
    "rejected_protected_file": _Expected(
        terminal="done", changes={},
        answer_contains=("rejected",), answer_forbid=("updated budget_final",),
        require_rejected=True,
    ),
    "create_new_file": _Expected(
        terminal="done",
        changes={"unique.txt": "ada\nzoe\n"},
    ),
    "delete_build_artifact_auto_ok": _Expected(
        terminal="done", changes={"build/output.log": None},
        forbid_error=True,
    ),
    "read_only_question": _Expected(
        terminal="done", changes={}, answer_patterns=(r"\bretry\b\D{0,48}(?<!\d)2(?!\d)",),
    ),
    "ambiguous_general_target": _Expected(
        terminal="ask", changes={},
        answer_contains=("task_notes.md", "meeting_notes.md"),
    ),
    "exact_match_required_edit": _Expected(
        terminal="done",
        changes={"code.py": "def say_hello(name):\n    return f'hi {name}'\n\n\ngreet('x')\n"},
        answer_contains=("say_hello",),
    ),
}


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    """Score one finished trajectory for ``task``. Returns a list of failure reasons (empty = pass).

    ``changes``: path -> staged UTF-8 text, or None for a staged deletion.
    ``events``: sequence of (parsed protocol.Action, rendered observation text, is_error).
    ``original_unchanged``: True iff nothing outside the staged ``changes`` moved underneath
    the task (a runner-computed fact, trusted here, not recomputed).
    """
    try:
        spec = _EXPECTED[task.id]
    except KeyError:
        return [f"no grading spec registered for task id {task.id!r}"]

    reasons = []
    if not original_unchanged:
        reasons.append("workspace changed outside the staged changes")

    if terminal != spec.terminal:
        reasons.append(f"terminal: expected {spec.terminal!r}, got {terminal!r}")

    text = answer or ""
    low = text.lower()
    for needle in spec.answer_contains:
        if needle.lower() not in low:
            reasons.append(f"answer is missing expected content {needle!r}: {text!r}")
    for needle in spec.answer_forbid:
        if needle.lower() in low:
            reasons.append(f"answer falsely claims {needle!r}: {text!r}")
    for pattern in spec.answer_patterns:
        if not re.search(pattern, text, re.IGNORECASE):
            reasons.append(f"answer does not state the expected value ({pattern}): {text!r}")

    if changes != spec.changes:
        reasons.append(f"changes mismatch: expected {spec.changes!r}, got {changes!r}")

    observations = [obs for _, obs, _ in events]
    errors = [is_error for _, _, is_error in events]
    if spec.require_pending and not any("pending" in o.lower() for o in observations):
        reasons.append("expected a pending policy observation as evidence of the approval gate")
    if spec.require_rejected and not any("reject" in o.lower() for o in observations):
        reasons.append("expected a rejected policy observation as evidence of the reject gate")
    if spec.require_error and not any(errors):
        reasons.append("expected at least one error observation (recovery evidence)")
    if spec.forbid_error and any(errors):
        reasons.append("unexpected error observation")

    return reasons
