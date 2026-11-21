import pytest

from lilguy.sandbox.backend import DiffEntry


def test_protected_paths_are_rejected_before_approval():
    from lilguy.policy.engine import evaluate
    decision = evaluate([DiffEntry("modified", ".git/config", "file")], [])
    assert decision.kind == "reject"
    assert decision.rule == "protected"


def test_one_deleted_source_file_requires_approval_by_default():
    from lilguy.policy.engine import evaluate
    decision = evaluate([DiffEntry("deleted", "src/main.c", "file")], [])
    assert decision.kind == "pending"


def test_accumulated_deletions_exceed_limit_even_when_each_step_does_not():
    from lilguy.policy.engine import evaluate
    deletes = [DiffEntry("deleted", f"build/{n}", "file") for n in range(30)]
    decision = evaluate(deletes[:15], deletes)
    # build outputs are exempt in default policy; this case overrides exemption.
    from lilguy.policy.engine import Policy
    decision = evaluate(deletes[:15], deletes, Policy(delete_free_paths=(), any_delete_outside=None))
    assert decision.kind == "pending"
    assert decision.rule == "max_deletes"


def test_permission_removal_requires_approval_even_without_execute_change():
    from lilguy.policy.engine import evaluate
    entry = DiffEntry("meta", "src/main.c", "file", mode_before=0o644, mode_after=0)
    assert evaluate([entry], []).kind == "pending"


def test_special_file_rejection_wins_over_delete_pending_in_other_view():
    from lilguy.policy.engine import evaluate
    assert evaluate([DiffEntry("deleted", "src/a", "file")],
                    [DiffEntry("added", "fifo", "special")]).kind == "reject"


def test_workspace_cannot_loosen_server_policy():
    from lilguy.policy.engine import Policy, evaluate_policies
    entries = [DiffEntry("modified", ".env", "file")]
    assert evaluate_policies(entries, entries, [Policy(), Policy(protected=())]).kind == "reject"


def test_policy_refuses_unknown_fields(tmp_path):
    from lilguy.policy.engine import load_policy
    policy = tmp_path / "policy.yaml"
    policy.write_text("auto_commit:\n  max_deletttes: 100\n")
    with pytest.raises(ValueError):
        load_policy(policy)


def test_read_only_policy_rejects_any_staged_change():
    from lilguy.policy.engine import Policy, evaluate, evaluate_policies, active_policies
    ro = Policy(read_only=True)
    for entry in (DiffEntry("added", "out.txt", "file"), DiffEntry("modified", "a.txt", "file"),
                  DiffEntry("deleted", "build/x", "file"), DiffEntry("meta", "run.sh", "file", mode_before=0o644,
                                                                      mode_after=0o755)):
        decision = evaluate([entry], [entry], ro)
        assert (decision.kind, decision.rule, decision.detail) == ("reject", "read_only", f"read-only question: {entry.path}")
    assert evaluate([], [], ro).kind == "ok"
    assert evaluate_policies([DiffEntry("added", "x", "file")], [], active_policies([ro])).rule == "read_only"
    assert Policy().read_only is False


def test_read_only_cannot_be_switched_by_workspace_yaml(tmp_path):
    from lilguy.policy.engine import load_policy
    (tmp_path / "p.yaml").write_text("read_only: true\n")
    with pytest.raises(ValueError):
        load_policy(tmp_path / "p.yaml")
