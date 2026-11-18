"""Which policy layers may relax what (spec: workspace config cannot weaken server config)."""
from lilguy.policy.engine import MANDATORY, Policy, active_policies, evaluate_policies
from lilguy.sandbox.backend import DiffEntry


def deletes(n, prefix="src"):
    return [DiffEntry("deleted", f"{prefix}/f{i}.c", "file", size_before=1) for i in range(n)]


def test_trusted_config_may_turn_off_per_delete_approval_and_rely_on_the_total():
    trusted = Policy(any_delete_outside=None)
    first_step = deletes(15)
    assert evaluate_policies(first_step, first_step, active_policies([trusted])).kind == "ok"
    session = deletes(30)
    decision = evaluate_policies(deletes(15), session, active_policies([trusted]))
    assert (decision.kind, decision.rule) == ("pending", "max_deletes")


def test_without_trusted_config_the_spec_defaults_apply():
    decision = evaluate_policies(deletes(1), deletes(1), active_policies(None))
    assert (decision.kind, decision.rule) == ("pending", "any_delete_outside")


def test_trusted_config_cannot_unprotect_or_allow_special_files():
    lax = Policy(protected=(), special_files=False, any_delete_outside=None)
    env = [DiffEntry("added", ".env", "file", size_after=1)]
    assert evaluate_policies(env, env, active_policies([lax])).kind == "reject"
    fifo = [DiffEntry("added", "pipe", "special")]
    assert evaluate_policies(fifo, fifo, active_policies([lax])).kind == "reject"


def test_trusted_config_cannot_skip_conflicts():
    lax = Policy(any_delete_outside=None)
    entries = [DiffEntry("added", "a", "file", size_after=1)]
    decision = evaluate_policies(entries, entries, active_policies([lax]), conflict=True)
    assert decision.rule == "conflict"


def test_workspace_config_only_tightens():
    trusted = Policy(any_delete_outside=None)
    workspace = Policy(any_delete_outside=None, max_deletes=1000)
    two = deletes(2)
    assert evaluate_policies(two, two, active_policies([trusted], workspace=workspace)).kind == "ok"
    strict = Policy(max_deletes=1, any_delete_outside=None)
    assert evaluate_policies(two, two, active_policies([trusted], workspace=strict)).rule == "max_deletes"
    many = deletes(30)
    # The workspace's own higher limit does not lift the trusted limit.
    assert evaluate_policies(many, many, active_policies([trusted], workspace=workspace)).rule == "max_deletes"


def test_mandatory_floor_only_rejects():
    for entries in (deletes(500), [DiffEntry("modified", "x", "file", size_before=5, size_after=0)]):
        assert evaluate_policies(entries, entries, [MANDATORY]).kind == "ok"
