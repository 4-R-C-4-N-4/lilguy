"""Interface-v2 grading on the development harness: answers are graded only where an answer is
the deliverable (no staged change, no policy stop); change tasks are graded on effects."""
from lilguy import protocol as p
from dev import fast12_runner as r

TOOLS = p.load_tools()


def _grade(task, *, terminal, answer, changes, events, original_unchanged):
    reasons = [] if changes == {"a.txt": "x"} else ["staged effects differ from expected output"]
    if "ready" not in (answer or ""):
        reasons.append("answer is missing expected content 'ready'")
    if terminal != "done":
        reasons.append("expected done")
    return reasons


def test_answer_reasons_are_dropped_only_when_no_answer_is_required():
    lenient = r.interface_grade(_grade, answer_required=False, version=2)
    assert lenient(None, terminal="done", answer="", changes={"a.txt": "x"}, events=[],
                   original_unchanged=True) == []
    assert lenient(None, terminal="ask", answer="", changes={}, events=[], original_unchanged=True) == [
        "staged effects differ from expected output", "expected done"]
    strict = r.interface_grade(_grade, answer_required=True, version=2)
    assert "answer is missing expected content 'ready'" in strict(
        None, terminal="done", answer="", changes={"a.txt": "x"}, events=[], original_unchanged=True)
    assert r.interface_grade(_grade, answer_required=False, version=1) is _grade


def test_every_answer_reason_wording_used_by_the_suites_is_recognised():
    for reason in ("answer is missing expected content 'x': ''", "answer falsely claims 'x': ''",
                   "answer does not state the expected value (x): ''", "answer omits an expected fact or choice",
                   "answer contradicts the requested result", "answer is missing the requested result",
                   "read-only answer lacks a successful tool observation",
                   "terminal answer must say approval is still needed", "terminal answer claims changes were applied"):
        assert r.is_answer_reason(reason), reason
    for reason in ("expected done", "staged effects differ from expected output", "unexpected policy stop",
                   "expected a rejected policy observation as evidence of the reject gate"):
        assert not r.is_answer_reason(reason), reason


def test_answer_required_follows_the_oracle_effects_and_policy():
    ok = "exit=0\n(no output)\nchanges: none\npolicy: ok"
    assert r.answer_required({"changes": {}, "events": [{"observation": ok}]})
    assert not r.answer_required({"changes": {"a": "x"}, "events": [{"observation": ok}]})
    assert not r.answer_required({"changes": {}, "events": [{"observation": ok.replace("ok", "rejected (a)")}]})


def test_the_model_request_follows_the_interface_version(monkeypatch):
    import inspect
    source = inspect.getsource(r.run_model)
    assert "p.system_prompt(tools, version)" in source and "p.grammar(tools, version)" in source
    assert "p.parse_action(reply, tools, version)" in source


def test_dev_workspace_separates_the_terminal_from_the_answer_wording():
    from dev import dev_workspace
    task = next(t for t in dev_workspace.TASKS if t.policy_end != "ok")
    reasons = dev_workspace.grade(task, terminal="ask", answer="pending approval", changes=task.changes,
                                  events=[], original_unchanged=True)
    assert any(not r.is_answer_reason(x) and "done" in x for x in reasons)


def test_v3_grades_the_quoted_output_not_the_model_text():
    from dev import fast12_runner as fr
    from lilguy import protocol as p

    obs = p.render_observation(exit_code=0, stdout="5\n", policy="ok")
    seen = {}

    def grade(task, **kwargs):
        seen.update(kwargs)
        return [] if kwargs['answer'] == '5' else ['answer is missing expected content']

    task = type('T', (), {'files': {'access.log': 'a\nb\nc\nd\ne\n'}})()
    events = [(p.Action.run('wc -l < access.log'), obs, False)]
    graded = fr.interface_grade(grade, answer_required=True, version=3)
    assert graded(task, terminal='done', answer='', changes={}, events=events, original_unchanged=True) == []
    # Quoting a whole input file, or literal text the model typed, is not an answer.
    whole = [(p.Action.call('fs.read', path='access.log'),
              p.render_observation(exit_code=0, stdout='a\nb\nc\nd\ne\n', policy='ok'), False)]
    graded(task, terminal='done', answer='', changes={}, events=whole, original_unchanged=True)
    assert seen['answer'] == ''
    typed = [(p.Action.run('echo 5'), obs, False)]
    graded(task, terminal='done', answer='', changes={}, events=typed, original_unchanged=True)
    assert seen['answer'] == ''


def test_v3_mode_is_ask_exactly_for_the_listed_development_questions():
    from dev import broad_runner, fast12, fast12_runner as fr, oracles_v3
    roster = {t.id: t for t in (*fast12.TASKS, *(t for t, _ in broad_runner.task_graders()))}
    assert oracles_v3.ASK <= set(roster)
    assert {fr.task_mode(roster[i]) for i in oracles_v3.ASK} == {'ask'}
    assert fr.task_mode(roster['leave_matching_output_style']) == 'do'  # a change request
    assert fr.task_mode(roster['read_only_question'], version=2) == 'do'


def test_every_development_question_is_asked_from_v3():
    """A task that changes nothing and is graded on stated facts is a question: from interface v3 it
    must be issued with `ask`, ending on a command whose output answers it (batch 7 lesson)."""
    from dev import broad_runner, oracles_v3
    do_requests = {'leave_matching_output_style', 'withhold_copy_when_only_prefix_matches'}
    questions = {t.id for t, _ in broad_runner.task_graders()
                 if not getattr(t, 'changes', None) and getattr(t, 'facts', ()) and t.id not in do_requests}
    assert questions <= oracles_v3.ASK
