"""Unit-only grading for the dev/broad_dev.py suite: no shell, no model, no sandbox, no live
suites, no held-out data, no training.

Same contract as tests/unit/test_fast12.py, which this deliberately mirrors: each task's `oracle`
is interpreted by a tiny scripted executor built on the *real* lilguy.protocol parser and the
*real* lilguy.policy.engine decision logic, and the resulting trajectory is handed to
`broad_dev.grade`. Strict red-first: every task has at least one paired negative-control test
proving `grade` turns a wrong/false trajectory into a nonempty reason list.

The executor supports exactly the small, fixed vocabulary of `run` commands this batch's oracles
use (cp/mkdir, cut, grep, sort, comm) by computing their effect directly in Python against the
in-memory `files` dict -- never via subprocess or a host shell.
"""
from __future__ import annotations

from dev import broad_dev
from lilguy import protocol as p
from lilguy.policy import engine as pol
from lilguy.sandbox.backend import DiffEntry

import pytest

TOOLS = p.load_tools()


def _cut_column(files, path, delim, field_1based):
    idx = field_1based - 1
    out = []
    for line in files[path].splitlines():
        parts = line.split(delim)
        out.append((parts[idx] if idx < len(parts) else "") + "\n")
    return "".join(out)


RUN_HANDLERS = {
    "mkdir -p logs && cp app.log logs/app.log && cp error.log logs/error.log":
        lambda files: {"logs/app.log": files["app.log"], "logs/error.log": files["error.log"]},
    "mkdir -p archive && cp old_report.txt archive/old_report.txt":
        lambda files: {"archive/old_report.txt": files["old_report.txt"]},
    "cut -d, -f2 users.csv | tail -n +2 > emails.txt":
        lambda files: {"emails.txt": _cut_column(
            {"users.csv": "\n".join(files["users.csv"].splitlines()[1:])}, "users.csv", ",", 2)},
    "cut -d' ' -f1 logins.txt > usernames.txt":
        lambda files: {"usernames.txt": _cut_column(files, "logins.txt", " ", 1)},
    "grep ERROR server.log > errors.txt":
        lambda files: {"errors.txt": "".join(
            line for line in files["server.log"].splitlines(keepends=True) if "ERROR" in line)},
    "sort -n scores.txt > sorted_scores.txt":
        lambda files: {"sorted_scores.txt": "".join(
            sorted(files["scores.txt"].splitlines(keepends=True), key=lambda line: int(line.strip())))},
    "sort -r roster.txt > roster_sorted.txt":
        lambda files: {"roster_sorted.txt": "".join(
            sorted(files["roster.txt"].splitlines(keepends=True), reverse=True))},
    "comm -13 <(sort old_members.txt) <(sort new_members.txt) > added.txt":
        lambda files: {"added.txt": "".join(sorted(
            set(files["new_members.txt"].splitlines(keepends=True))
            - set(files["old_members.txt"].splitlines(keepends=True))))},
}


def run_oracle(task, actions=None):
    """Interpret a sequence of v1 action strings against task.files using the real protocol
    parser and the real policy engine. Returns (terminal, answer, changes, events,
    original_unchanged) exactly as broad_dev.grade expects them."""
    files = dict(task.files)
    changes = {}
    events = []
    session_entries = []
    terminal = "invalid"
    answer = None
    policies = pol.active_policies([pol.Policy()])

    def decide(path, before, after, op):
        entry = DiffEntry(op=op, path=path, kind="file",
                           size_before=len(before.encode()) if before is not None else None,
                           size_after=len(after.encode()) if after is not None else None)
        return entry, pol.evaluate_policies([entry], session_entries + [entry], policies)

    def stage(path, content):
        before = files.get(path)
        entry, decision = decide(path, before, content, "modified" if before is not None else "added")
        if decision.kind == "reject":
            return f"policy: rejected ({decision.rule})", True
        files[path] = content
        changes[path] = content
        session_entries.append(entry)
        return f"policy: {decision.kind}" + (f" ({decision.rule})" if decision.rule else ""), False

    for raw in (actions if actions is not None else task.oracle):
        action = p.parse_action(raw, TOOLS, 2)
        if action.kind == "ask":
            terminal, answer = "ask", action.text
            events.append((action, "", False))
            break
        if action.kind == "done":
            terminal, answer = "done", action.text
            events.append((action, "", False))
            break
        if action.kind == "tool":
            path = action.args.get("path", ".")
            if action.tool == "fs.read" and path not in files:
                events.append((action, f"error: {path} not found", True))
                continue
            events.append((action, "ok", False))
            continue
        if action.kind == "run" and action.text in RUN_HANDLERS:
            outputs = RUN_HANDLERS[action.text](files)
            is_error = False
            obs_parts = []
            for path, content in outputs.items():
                obs, err = stage(path, content)
                obs_parts.append(obs)
                is_error = is_error or err
            events.append((action, "; ".join(obs_parts), is_error))
            continue
        events.append((action, "error: unsupported in the broad_dev scripted executor", True))
        terminal = "tool-error"
        break

    touched = set(changes)
    original_unchanged = all(files.get(path) == task.files.get(path)
                              for path in set(files) | set(task.files) if path not in touched)
    return terminal, answer, changes, events, original_unchanged


def _run_and_grade(task, actions=None):
    terminal, answer, changes, events, unchanged = run_oracle(task, actions)
    return broad_dev.grade(task, terminal=terminal, answer=answer, changes=changes,
                            events=events, original_unchanged=unchanged)


def _task(task_id):
    return next(t for t in broad_dev.TASKS if t.id == task_id)


# --- structural sanity -----------------------------------------------------------------------

def test_twelve_distinct_tasks():
    assert len(broad_dev.TASKS) == 12
    ids = [t.id for t in broad_dev.TASKS]
    assert len(set(ids)) == 12


def test_distinct_from_fast12_task_identities():
    from dev import fast12
    assert set(t.id for t in broad_dev.TASKS).isdisjoint(t.id for t in fast12.TASKS)


def test_every_task_has_a_grading_spec():
    for task in broad_dev.TASKS:
        assert task.id in broad_dev._EXPECTED


def test_oracle_actions_all_parse_as_v1():
    for task in broad_dev.TASKS:
        for raw in task.oracle:
            p.parse_action(raw, TOOLS, 2)  # raises ProtocolError on anything malformed


def test_every_task_is_non_destructive():
    """This batch never deletes or overwrites pre-existing content -- fast12 owns that territory."""
    for task in broad_dev.TASKS:
        spec = broad_dev._EXPECTED[task.id]
        for path, content in spec.changes.items():
            assert content is not None, f"{task.id}: unexpected staged deletion of {path}"
            assert path not in task.files, f"{task.id}: change overwrites a pre-existing file"


# --- green path: every task's own oracle must grade clean ------------------------------------

@pytest.mark.parametrize("task", broad_dev.TASKS, ids=[t.id for t in broad_dev.TASKS])
def test_oracle_passes_its_own_task(task):
    reasons = _run_and_grade(task)
    assert reasons == [], reasons


# --- red-first: each task must have a paired negative control --------------------------------

def test_count_lines_total_rejects_a_wrong_count():
    task = _task("count_lines_total")
    wrong = ("tool fs.read\npath: access.log", "done\nThere are 4 lines in access.log.")
    reasons = _run_and_grade(task, wrong)
    assert any("missing expected content" in r for r in reasons)


def test_count_matching_rows_rejects_a_wrong_count():
    task = _task("count_matching_rows")
    wrong = ("tool fs.read\npath: orders.csv", "done\n3 rows have status 'pending'.")
    reasons = _run_and_grade(task, wrong)
    assert any("missing expected content" in r for r in reasons)


def test_organize_logs_rejects_claiming_a_move_when_oracle_is_a_copy():
    task = _task("organize_logs_into_dir")
    false_claim = (
        "run\nmkdir -p logs && cp app.log logs/app.log && cp error.log logs/error.log",
        "done\nMoved app.log and error.log into logs/.",
    )
    reasons = _run_and_grade(task, false_claim)
    assert any("falsely claims" in r for r in reasons)


def test_organize_logs_rejects_skipping_one_file():
    task = _task("organize_logs_into_dir")
    partial = (
        "run\nmkdir -p logs && cp app.log logs/app.log",
        "done\nCopied app.log and error.log into logs/.",
    )
    reasons = _run_and_grade(task, partial)
    assert any("terminal" in r for r in reasons) or any("changes mismatch" in r for r in reasons)


def test_archive_old_report_rejects_a_false_deletion_claim():
    task = _task("archive_old_report")
    false_claim = (
        "run\nmkdir -p archive && cp old_report.txt archive/old_report.txt",
        "done\nDeleted old_report.txt and moved it to archive/.",
    )
    reasons = _run_and_grade(task, false_claim)
    assert any("falsely claims" in r for r in reasons)


def test_extract_email_column_rejects_including_the_header():
    task = _task("extract_email_column")
    wrong = (
        "run\ncut -d, -f2 users.csv > emails.txt",  # header not stripped
        "done\nWrote the email column from users.csv to emails.txt, header excluded.",
    )
    reasons = _run_and_grade(task, wrong)
    assert any("terminal" in r for r in reasons)


def test_extract_first_field_rejects_the_wrong_delimiter_result():
    task = _task("extract_first_field_space_separated")
    wrong_changes = {"usernames.txt": "alice 10:00\nbob 10:05\ncarl 10:10\n"}  # whole lines, no cut
    reasons = broad_dev.grade(task, terminal="done",
                               answer="Wrote the usernames from logins.txt to usernames.txt.",
                               changes=wrong_changes, events=[], original_unchanged=True)
    assert any("changes mismatch" in r for r in reasons)


def test_find_lines_with_error_rejects_a_wrong_match_count():
    task = _task("find_lines_with_error")
    wrong = (
        "run\ngrep ERROR server.log > errors.txt",
        "done\nWrote the 3 ERROR lines from server.log to errors.txt.",
    )
    reasons = _run_and_grade(task, wrong)
    assert any("missing expected content" in r for r in reasons)


def test_find_todo_comments_rejects_naming_the_wrong_file():
    task = _task("find_todo_comments")
    wrong = (
        "tool fs.read\npath: a.py",
        "tool fs.read\npath: b.py",
        "done\na.py contains a TODO comment; b.py does not.",
    )
    reasons = _run_and_grade(task, wrong)
    assert any("missing expected content" in r for r in reasons) or any(
        "falsely claims" in r for r in reasons)


def test_sort_numbers_ascending_rejects_lexicographic_sort():
    task = _task("sort_numbers_ascending")
    lexicographic = {"sorted_scores.txt": "100\n2\n30\n5\n"}
    reasons = broad_dev.grade(task, terminal="done", answer="sorted",
                               changes=lexicographic, events=[], original_unchanged=True)
    assert any("changes mismatch" in r for r in reasons)


def test_sort_names_reverse_rejects_forward_sort():
    task = _task("sort_names_reverse")
    forward = {"roster_sorted.txt": "alice\nbob\ncarl\n"}
    reasons = broad_dev.grade(task, terminal="done", answer="sorted",
                               changes=forward, events=[], original_unchanged=True)
    assert any("changes mismatch" in r for r in reasons)


def test_diff_two_lists_added_rejects_a_wrong_name_list():
    task = _task("diff_two_lists_added")
    wrong = (
        "run\ncomm -13 <(sort old_members.txt) <(sort new_members.txt) > added.txt",
        "done\nalice and bob are new; wrote them to added.txt.",
    )
    reasons = _run_and_grade(task, wrong)
    assert any("missing expected content" in r for r in reasons)


def test_compare_file_sizes_answer_rejects_the_wrong_byte_delta():
    task = _task("compare_file_sizes_answer")
    wrong = (
        "tool fs.read\npath: small.txt",
        "tool fs.read\npath: big.txt",
        "done\nbig.txt is larger than small.txt by 5 bytes.",
    )
    reasons = _run_and_grade(task, wrong)
    assert any("missing expected content" in r for r in reasons)


# --- genuinely-computed evidence (guards against the executor rubber-stamping) ---------------

def test_diff_two_lists_added_is_really_computed_not_asserted():
    task = _task("diff_two_lists_added")
    _, _, changes, _, _ = run_oracle(task)
    assert changes == {"added.txt": "carl\ndan\n"}


def test_extract_email_column_is_really_computed_not_asserted():
    task = _task("extract_email_column")
    _, _, changes, _, _ = run_oracle(task)
    assert changes == {"emails.txt": "alice@x.com\nbob@x.com\ncarl@x.com\n"}


def test_workspace_touched_outside_declared_changes_is_always_a_failure():
    task = _task("sort_numbers_ascending")
    reasons = broad_dev.grade(task, terminal="done", answer="sorted",
                               changes={"sorted_scores.txt": "2\n5\n30\n100\n"},
                               events=[], original_unchanged=False)
    assert any("outside the staged changes" in r for r in reasons)


def test_grade_reports_unknown_task_id_instead_of_crashing():
    bogus = broad_dev.Task(id="not-a-real-task", request="x", files={}, oracle=())
    reasons = broad_dev.grade(bogus, terminal="done", answer="x", changes={}, events=[],
                               original_unchanged=True)
    assert reasons and "no grading spec" in reasons[0]
