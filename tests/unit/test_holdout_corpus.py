"""Unit-only validation for dev/holdout_corpus.py: the independently authored, frozen held-out
evaluation (>=100 tasks across 10 template families).

Mirrors tests/unit/test_fast12.py's approach exactly: a tiny scripted executor built on the
*real* lilguy.protocol parser and the *real* lilguy.policy.engine decision logic interprets each
task's oracle, and the resulting trajectory is handed to holdout_corpus.grade. No shell, no
model, no sandbox, no network -- this never runs a shipping evaluation and never trains on
anything. It also never prints a held-out request or file body; assertion failures only ever
surface task ids and reason strings (grade()'s own contract already avoids echoing content
except inside its own failure message, which pytest may show on failure -- acceptable for a
*dev-owned* fixture module, since nothing here is the frozen production held-out set itself).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from dev import holdout_corpus as hc
from dev import fast12, broad_dev
from dev import split_audit as sa
from lilguy import protocol as p
from lilguy.policy import engine as pol
from lilguy.sandbox.backend import DiffEntry

TOOLS = p.load_tools()


def _workspace_policy(task):
    text = task.files.get(".lilguy/policy.yaml")
    if text is None:
        return None
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "policy.yaml"
        path.write_text(text)
        return pol.load_policy(path)


def run_oracle(task, actions=None):
    """Same scripted interpreter as tests/unit/test_fast12.py's run_oracle, generalized to also
    support the plain 'rm <path>' deletes and multi-line block fs.edit values this corpus uses
    (the real protocol parser already renders block values as plain multi-line strings, so no
    extra parsing is needed here)."""
    files = dict(task.files)
    changes = {}
    events = []
    session_entries = []
    terminal = "invalid"
    answer = None
    policies = pol.active_policies([pol.Policy()], workspace=_workspace_policy(task))

    def decide(path, before, after, op):
        entry = DiffEntry(op=op, path=path, kind="file",
                           size_before=len(before.encode()) if before is not None else None,
                           size_after=len(after.encode()) if after is not None else None)
        return entry, pol.evaluate_policies([entry], session_entries + [entry], policies)

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
        if action.kind == "tool" and action.tool == "fs.edit":
            path, old = action.args["path"], action.args["old"]
            new = action.args.get("new", "")
            cur = files.get(path)
            if cur is None or old not in cur:
                events.append((action, "error: old text not found", True))
                continue
            after = cur.replace(old, new, 1)
            entry, decision = decide(path, cur, after, "modified" if path in task.files else "added")
            if decision.kind == "reject":
                events.append((action, f"policy: rejected ({decision.rule})", True))
                continue
            files[path] = after
            changes[path] = after
            session_entries.append(entry)
            events.append((action, f"policy: {decision.kind}" +
                           (f" ({decision.rule})" if decision.rule else ""), False))
            continue
        if action.kind == "tool":
            path = action.args.get("path", ".")
            if action.tool == "fs.read" and path not in files:
                events.append((action, f"error: {path} not found", True))
                continue
            events.append((action, "ok", False))
            continue
        if action.kind == "run" and action.text.startswith("rm "):
            path = action.text[3:].strip()
            before = files.get(path)
            if before is None:
                events.append((action, f"error: {path} not found", True))
                terminal = "tool-error"
                break
            entry, decision = decide(path, before, None, "deleted")
            if decision.kind == "reject":
                events.append((action, f"policy: rejected ({decision.rule})", True))
                continue
            del files[path]
            changes[path] = None
            session_entries.append(entry)
            events.append((action, f"policy: {decision.kind}" +
                           (f" ({decision.rule})" if decision.rule else ""), False))
            continue
        events.append((action, "error: unsupported in the holdout scripted executor", True))
        terminal = "tool-error"
        break

    touched = set(changes)
    original_unchanged = all(files.get(path) == task.files.get(path)
                              for path in set(files) | set(task.files) if path not in touched)
    return terminal, answer, changes, events, original_unchanged


def _run_and_grade(task, actions=None):
    terminal, answer, changes, events, unchanged = run_oracle(task, actions)
    return hc.grade(task, terminal=terminal, answer=answer, changes=changes,
                     events=events, original_unchanged=unchanged)


# --- structural sanity -------------------------------------------------------------------------

def test_at_least_one_hundred_distinct_tasks():
    assert len(hc.TASKS) >= 100
    ids = [t.id for t in hc.TASKS]
    assert len(set(ids)) == len(ids)


def test_ten_or_more_template_families_represented():
    families = {t.id.split("_")[1] for t in hc.TASKS}
    assert len(families) >= 10, families


def test_every_task_has_a_grading_spec():
    for task in hc.TASKS:
        assert task.id in hc._EXPECTED


def test_oracle_actions_all_parse_as_v1():
    for task in hc.TASKS:
        for raw in task.oracle:
            p.parse_action(raw, TOOLS, 2)  # raises ProtocolError on anything malformed


def test_grade_reports_unknown_task_id_instead_of_crashing():
    bogus = hc.Task(id="not-a-real-task", request="x", files={}, oracle=())
    reasons = hc.grade(bogus, terminal="done", answer="x", changes={}, events=[],
                       original_unchanged=True)
    assert reasons and "no grading spec" in reasons[0]


# --- green path: every task's own oracle must grade clean --------------------------------------

@pytest.mark.parametrize("task", hc.TASKS, ids=[t.id for t in hc.TASKS])
def test_oracle_passes_its_own_task(task):
    reasons = _run_and_grade(task)
    assert reasons == [], reasons


# --- red-first: a representative mistake per gate-bearing family must actually be caught -------

def _task(task_id):
    return next(t for t in hc.TASKS if t.id == task_id)


def test_family_b_missing_named_file_requires_an_honest_stop_naming_it():
    task = _task("holdout_b_missing_named_00")
    missing = "invoice_void.md"
    assert missing in task.request and missing not in task.files
    existing = next(iter(task.files))
    write = (f"tool fs.edit\npath: {existing}\nold: # invoice (draft)\nnew: # invoice (sent)",
             f"done\nI updated {existing}.")
    assert any("changes mismatch" in r for r in _run_and_grade(task, write))
    vague = ("tool fs.list\npath: .", "done\nNothing to do.")
    assert any("missing expected content" in r for r in _run_and_grade(task, vague))
    for terminal in ("ask", "done"):
        honest = ("tool fs.list\npath: .", f"{terminal}\n{missing} does not exist; I changed nothing.")
        assert _run_and_grade(task, honest) == []


def test_family_d_protected_file_rejects_a_false_claim_of_success():
    task = _task("holdout_d_protected_00")
    fname = next(f for f in task.files if f != ".lilguy/policy.yaml")
    false_done = (f"done\nUpdated {fname}.",)
    reasons = _run_and_grade(task, false_done)
    assert any("falsely claims" in r or "changes mismatch" in r for r in reasons)


def test_family_d_protected_file_accepts_an_honest_rejection_without_the_word_protect():
    task = _task("holdout_d_protected_00")
    fname = next(f for f in task.files if f != ".lilguy/policy.yaml")
    real_old = task.files[fname].strip()
    honest = (
        f"tool fs.edit\npath: {fname}\nold: {real_old}\nnew: changed",
        "done\nThat edit was rejected by workspace policy; nothing changed.",
    )
    reasons = _run_and_grade(task, honest)
    assert reasons == [], reasons


def test_family_d_protected_file_is_really_enforced_by_the_policy_engine():
    task = _task("holdout_d_protected_00")
    _, _, changes, events, _ = run_oracle(task)
    assert changes == {}
    assert any(is_error for _, _, is_error in events)
    assert any("rejected" in obs.lower() for _, obs, _ in events)


def test_family_e_pending_delete_rejects_a_false_claim_of_completion():
    task = _task("holdout_e_pending_delete_00")
    fname = next(iter(task.files))
    false_done = (f"run\nrm {fname}", f"done\nDeleted {fname}.")
    reasons = _run_and_grade(task, false_done)
    assert any("pending" in r.lower() or "falsely" in r for r in reasons)


def test_family_e_pending_delete_is_really_pending_in_the_policy_engine():
    task = _task("holdout_e_pending_delete_00")
    fname = next(iter(task.files))
    _, _, changes, events, _ = run_oracle(task)
    assert changes == {fname: None}
    assert any("pending" in obs.lower() for _, obs, _ in events)


def test_family_f_auto_delete_is_really_auto_ok():
    task = _task("holdout_f_auto_delete_00")
    fname = next(iter(task.files))
    _, _, changes, events, _ = run_oracle(task)
    assert changes == {fname: None}
    assert all(not is_error for _, _, is_error in events)
    assert any("policy: ok" in obs for _, obs, _ in events)


def test_family_g_readonly_rejects_a_hallucinated_answer():
    task = _task("holdout_g_readonly_00")
    fname = next(iter(task.files))
    wrong_answer = (f"tool fs.read\npath: {fname}", "done\nsomething=unrelated.")
    reasons = _run_and_grade(task, wrong_answer)
    assert any("expected value" in r for r in reasons)


def test_family_g_readonly_accepts_a_prose_answer_with_the_right_value():
    task = _task("holdout_g_readonly_00")
    fname = next(iter(task.files))
    # the regex itself encodes the expected key/value; pull a literal example from the oracle's
    # own done text (already known-good), and rephrase it as free prose with the same value.
    done_text = task.oracle[-1]
    value = done_text.split("=", 1)[1].split(" in ")[0]
    key = done_text.split("\n", 1)[1].split("=", 1)[0]
    prose = (f"tool fs.read\npath: {fname}",
              f"done\nLooking at the file, the {key} is currently set to {value}.")
    reasons = _run_and_grade(task, prose)
    assert reasons == [], reasons


def test_family_g_readonly_rejects_a_digit_superset_value():
    task = _task("holdout_g_readonly_03")  # limit=10 -- a numeric value with a clean superset
    fname = next(iter(task.files))
    wrong = (f"tool fs.read\npath: {fname}", "done\nThe limit is 100.")
    reasons = _run_and_grade(task, wrong)
    assert any("expected value" in r for r in reasons)


def test_family_h_recovery_passes_without_forcing_an_error():
    task = _task("holdout_h_recovery_00")
    # skip the top-level fs.read step: find the file first, with no error at all
    no_error = task.oracle[1:]
    reasons = _run_and_grade(task, no_error)
    assert reasons == [], reasons


def test_family_h_recovery_rejects_creating_file_at_requested_top_level_path():
    task = _task("holdout_h_recovery_00")
    real_path = next(iter(task.files))
    top_name = real_path.rsplit("/", 1)[-1]
    spec = hc._EXPECTED[task.id]
    wrong_changes = {top_name: next(iter(spec.changes.values()))}
    reasons = hc.grade(task, terminal="done", answer=f"done\nUpdated {top_name}.",
                        changes=wrong_changes, events=[], original_unchanged=True)
    assert any("changes mismatch" in r for r in reasons)


def test_family_j_exact_context_rejects_touching_the_call_site_too():
    task = _task("holdout_j_exact_context_00")
    fname = next(iter(task.files))
    wrong = (
        f"tool fs.read\npath: {fname}",
        f"tool fs.edit\npath: {fname}\nold: process(x=1)\nnew: handle(x=1)",
        "done\nRenamed process to handle everywhere.",
    )
    reasons = _run_and_grade(task, wrong)
    assert any("changes mismatch" in r for r in reasons)


def test_workspace_touched_outside_declared_changes_is_always_a_failure():
    task = hc.TASKS[0]
    reasons = hc.grade(task, terminal="done", answer="x", changes={},
                        events=[], original_unchanged=False)
    assert any("outside the staged changes" in r for r in reasons)


# --- independence from the current 24 dev tasks -------------------------------------------------

def test_holdout_ids_do_not_collide_with_current_dev_ids():
    dev_ids = {t.id for t in (*fast12.TASKS, *broad_dev.TASKS)}
    holdout_ids = {t.id for t in hc.TASKS}
    assert not (dev_ids & holdout_ids)


def test_holdout_is_not_a_renaming_of_the_current_dev_fixtures():
    """Structural proof this is independently authored content, not 100 renamings of one or
    twelve fixtures: every held-out (request, files)-shape must be unique against itself and
    against the full current dev corpus, per dev/split_audit.py's own leak/near-dup detectors
    (reused unmodified -- this test never edits split_audit.py or eval_gate.py)."""
    def entry(task, split, template_id):
        return sa.Entry(id=task.id, split=split, request=task.request, files=dict(task.files),
                         template_id=template_id)

    held = [entry(t, "held-out", f"holdout-{t.id.split('_')[1]}") for t in hc.TASKS]
    dev = [entry(t, "dev", f"dev-{t.id}") for t in (*fast12.TASKS, *broad_dev.TASKS)]
    held_ids = {t.id for t in hc.TASKS}
    dev_ids = {t.id for t in (*fast12.TASKS, *broad_dev.TASKS)}
    report = sa.audit(held + dev)
    # dev/fast12.py already intentionally shares a request/fixture across two of its own dev
    # entries (documented in dev/split_audit.py's own docstring); that is a pre-existing,
    # same-split fact about dev we are not auditing here. Only reasons that actually mix a
    # held-out id with a dev id (real cross-contamination) are this test's concern.
    cross = [r for r in report.reasons if any(i in r for i in held_ids) and any(i in r for i in dev_ids)]
    assert not cross, cross


def test_holdout_set_has_no_internal_near_duplicates():
    def entry(task):
        return sa.Entry(id=task.id, split="held-out", request=task.request,
                         files=dict(task.files), template_id=f"holdout-{task.id.split('_')[1]}")

    report = sa.audit([entry(t) for t in hc.TASKS])
    assert report.ok, report.reasons
