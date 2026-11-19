"""A second, broader 12-task development suite for fast unit-level grading of lilguy interface v1
trajectories, additional to dev/fast12.py (which stays unchanged).

Same shape and contract as fast12.py: each task is a small, disposable dev-loop fixture (``files``,
``request``, ``oracle``), and ``grade`` scores *any* finished trajectory against the task's
expectations without running a model or a shell. This module intentionally has no sandbox/runner
dependency either: nothing here executes a shell command or a model.

Where fast12 leans on everyday file-edit/approval scenarios, this batch covers everyday *read and
transform* shell idioms that fast12 does not: counting things, organizing files into folders,
extracting columns, finding text, sorting, and comparing two sources. Every task here is
non-destructive -- no task deletes or overwrites an existing file; "file organization" tasks copy
into a new location and leave the originals in place, so grading never has to reason about a
deletion-approval gate (that's fast12's territory).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: str
    request: str
    files: dict           # relative path -> initial text
    oracle: tuple          # sequence of v1 action strings (see lilguy.protocol.render_action)


@dataclass(frozen=True)
class _Expected:
    """What a passing trajectory for one task must look like. See dev/fast12.py for the full
    rationale; this mirrors that module's internal grading-detail dataclass field for field."""
    terminal: str
    changes: dict                 # path -> expected staged text, or None for a staged deletion
    answer_contains: tuple = ()   # substrings (case-insensitive) the final done/ask text must have
    answer_forbid: tuple = ()     # substrings it must NOT have (false claims of success)
    require_pending: bool = False
    require_rejected: bool = False
    require_error: bool = False
    forbid_error: bool = False


# --- the 12 tasks --------------------------------------------------------------------------------

TASKS = (
    Task(
        id="count_lines_total",
        request="How many lines are in access.log?",
        files={"access.log": "GET /\nGET /about\nPOST /login\nGET /home\nGET /logout\n"},
        oracle=(
            "tool fs.read\npath: access.log",
            "done\nThere are 5 lines in access.log.",
        ),
    ),
    Task(
        id="count_matching_rows",
        request="How many rows in orders.csv have status 'pending'?",
        files={"orders.csv": "id,status\n1,pending\n2,shipped\n3,pending\n4,delivered\n"},
        oracle=(
            "tool fs.read\npath: orders.csv",
            "done\n2 rows in orders.csv have status 'pending'.",
        ),
    ),
    Task(
        id="organize_logs_into_dir",
        request="Copy all .log files into a logs/ subdirectory, leaving the originals in place.",
        files={"app.log": "app started\n", "error.log": "disk full\n",
               "logs/README": "Keep existing logs here.\n"},
        oracle=(
            "tool fs.list\npath: .",
            "run\nmkdir -p logs && cp app.log logs/app.log && cp error.log logs/error.log",
            "done\nCopied app.log and error.log into logs/; the originals are untouched.",
        ),
    ),
    Task(
        id="archive_old_report",
        request="Copy old_report.txt into archive/, and keep the original where it is.",
        files={"old_report.txt": "Q1 summary\n", "archive/README": "Past reports.\n"},
        oracle=(
            "run\nmkdir -p archive && cp old_report.txt archive/old_report.txt",
            "done\nCopied old_report.txt into archive/old_report.txt; the original is still at "
            "old_report.txt.",
        ),
    ),
    Task(
        id="extract_email_column",
        request="Extract the email column from users.csv (no header) into emails.txt, one per line.",
        files={"users.csv": "name,email\nalice,alice@x.com\nbob,bob@x.com\ncarl,carl@x.com\n"},
        oracle=(
            "tool fs.read\npath: users.csv",
            "run\ncut -d, -f2 users.csv | tail -n +2 > emails.txt",
            "tool fs.read\npath: emails.txt",
            "done\nWrote the email column from users.csv to emails.txt, header excluded.",
        ),
    ),
    Task(
        id="extract_first_field_space_separated",
        request="Extract just the usernames (first space-separated field) from logins.txt into "
        "usernames.txt.",
        files={"logins.txt": "alice 10:00\nbob 10:05\ncarl 10:10\n"},
        oracle=(
            "run\ncut -d' ' -f1 logins.txt > usernames.txt",
            "done\nWrote the usernames from logins.txt to usernames.txt.",
        ),
    ),
    Task(
        id="find_lines_with_error",
        request="Write every line containing 'ERROR' from server.log into errors.txt.",
        files={"server.log": "INFO start\nERROR fail\nINFO ok\nERROR crash\nINFO done\n"},
        oracle=(
            "run\ngrep ERROR server.log > errors.txt",
            "done\nWrote the 2 ERROR lines from server.log to errors.txt.",
        ),
    ),
    Task(
        id="find_todo_comments",
        request="Which of a.py and b.py contains a TODO comment?",
        files={"a.py": "x = 1\n", "b.py": "# TODO: fix this\n"},
        oracle=(
            "tool fs.read\npath: a.py",
            "tool fs.read\npath: b.py",
            "done\nb.py contains a TODO comment; a.py does not.",
        ),
    ),
    Task(
        id="sort_numbers_ascending",
        request="Sort the numbers in scores.txt numerically ascending into sorted_scores.txt.",
        files={"scores.txt": "30\n5\n100\n2\n"},
        oracle=(
            "run\nsort -n scores.txt > sorted_scores.txt",
            "done\nWrote scores.txt sorted ascending to sorted_scores.txt.",
        ),
    ),
    Task(
        id="sort_names_reverse",
        request="Sort the names in roster.txt in reverse alphabetical order into roster_sorted.txt.",
        files={"roster.txt": "bob\nalice\ncarl\n"},
        oracle=(
            "run\nsort -r roster.txt > roster_sorted.txt",
            "done\nWrote roster.txt sorted reverse-alphabetically to roster_sorted.txt.",
        ),
    ),
    Task(
        id="diff_two_lists_added",
        request="Which names are in new_members.txt but not in old_members.txt? Write them to "
        "added.txt.",
        files={"old_members.txt": "alice\nbob\n", "new_members.txt": "alice\nbob\ncarl\ndan\n"},
        oracle=(
            "run\ncomm -13 <(sort old_members.txt) <(sort new_members.txt) > added.txt",
            "done\ncarl and dan are new; wrote them to added.txt.",
        ),
    ),
    Task(
        id="compare_file_sizes_answer",
        request="Which file is larger, small.txt or big.txt, and by how many bytes?",
        files={"small.txt": "hi\n", "big.txt": "hello world\n"},
        oracle=(
            "tool fs.read\npath: small.txt",
            "tool fs.read\npath: big.txt",
            "done\nbig.txt is larger than small.txt by 9 bytes.",
        ),
    ),
)

_EXPECTED = {
    "count_lines_total": _Expected(
        terminal="done", changes={}, answer_contains=("5",),
    ),
    "count_matching_rows": _Expected(
        terminal="done", changes={}, answer_contains=("2",),
    ),
    "organize_logs_into_dir": _Expected(
        terminal="done",
        changes={"logs/app.log": "app started\n", "logs/error.log": "disk full\n"},
        answer_contains=("logs/",), answer_forbid=("moved app.log", "removed app.log"),
    ),
    "archive_old_report": _Expected(
        terminal="done",
        changes={"archive/old_report.txt": "Q1 summary\n"},
        answer_contains=("archive",), answer_forbid=("moved old_report", "deleted old_report"),
    ),
    "extract_email_column": _Expected(
        terminal="done",
        changes={"emails.txt": "alice@x.com\nbob@x.com\ncarl@x.com\n"},
    ),
    "extract_first_field_space_separated": _Expected(
        terminal="done",
        changes={"usernames.txt": "alice\nbob\ncarl\n"},
    ),
    "find_lines_with_error": _Expected(
        terminal="done",
        changes={"errors.txt": "ERROR fail\nERROR crash\n"},
        answer_contains=("2",),
    ),
    "find_todo_comments": _Expected(
        terminal="done", changes={},
        answer_contains=("b.py",), answer_forbid=("a.py contains",),
    ),
    "sort_numbers_ascending": _Expected(
        terminal="done",
        changes={"sorted_scores.txt": "2\n5\n30\n100\n"},
    ),
    "sort_names_reverse": _Expected(
        terminal="done",
        changes={"roster_sorted.txt": "carl\nbob\nalice\n"},
    ),
    "diff_two_lists_added": _Expected(
        terminal="done",
        changes={"added.txt": "carl\ndan\n"},
        answer_contains=("carl", "dan"),
    ),
    "compare_file_sizes_answer": _Expected(
        terminal="done", changes={}, answer_contains=("big.txt", "9"),
    ),
}


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    """Score one finished trajectory for ``task``. Returns a list of failure reasons (empty = pass).

    Same contract as dev/fast12.py's ``grade``: ``changes`` is path -> staged UTF-8 text (or None
    for a staged deletion -- unused by this suite, since every task here is non-destructive);
    ``events`` is a sequence of (parsed protocol.Action, rendered observation text, is_error);
    ``original_unchanged`` is a runner-computed fact, trusted here, not recomputed.
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
