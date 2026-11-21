from dev import v1_pilot_data as data
from dev import v1_pilot_train as train
from lilguy import protocol as p


def test_pilot_fixtures_are_training_only_and_audit_with_every_dev_fixture():
    tasks = tuple(data.tasks())
    assert len(tasks) >= 16
    assert all(task.manifest()['split'] == 'train' for task in tasks)
    assert data.audit(tasks)['ok']


def test_bad_reference_effect_cannot_become_training_rows():
    task = next(data.tasks())
    trial = {'terminal': 'done', 'answer': 'Created output.', 'changes': {'wrong': 'wrong'},
             'original_unchanged': True, 'infra_error': None, 'failures': [], 'events': []}
    assert data.accept(task, trial, trial, p.load_tools()) is None


def test_changed_replay_is_not_admitted_even_with_identical_staged_effects():
    task = next(data.tasks())
    trial = {'terminal': 'done', 'answer': 'Created output.', 'changes': task.changes,
             'original_unchanged': True, 'infra_error': None, 'failures': [], 'events': []}
    assert data.accept(task, trial, {**trial, 'answer': 'different'}, p.load_tools()) is None


def test_training_rows_include_targets_at_each_assistant_turn():
    messages = [{ 'role': role, 'content': str(index)}
                for index, role in enumerate(('system', 'user', 'assistant', 'user', 'assistant'))]
    assert data.next_action_rows(messages) == [messages[:3], messages]


def test_training_refuses_unverified_data_and_wrong_base_revision(tmp_path):
    import pytest
    (tmp_path / 'train.jsonl').write_text('{"messages":[]}\n')
    with pytest.raises(ValueError, match='effect evidence'):
        train.verified_rows(tmp_path)
    with pytest.raises(ValueError, match='revision'):
        train.check_base(tmp_path)


def test_recovery_profile_requires_actual_failure_then_successful_read():
    tasks = tuple(data.tasks('recovery'))
    task = next(t for t in tasks if t.error_turns)
    request_tool = p.Action.call('fs.read', path='old-path')
    expect_value = task.read_evidence
    failed = (request_tool, p.render_observation(exit_code=1, stderr='not found'), True)
    listed = (p.Action.call('fs.list', path='.'), p.render_observation(exit_code=0), False)
    correct = (p.Action.call('fs.read', path='actual-path'),
               p.render_observation(exit_code=0, stdout=expect_value), False)
    facts = dict(terminal=task.terminal, answer=f'The ink colour is {expect_value}.',
                 changes={}, original_unchanged=True)
    assert not data._grade(task, events=[failed, listed, correct], **facts)
    assert data._grade(task, events=[failed, listed, correct], **{**facts, 'answer': 'Finished.'})
    assert data._grade(task, events=[listed, failed, correct], **facts)
    assert data._grade(task, events=[failed, listed], **facts)
    assert data._grade(task, events=[failed, listed, listed], **facts)
    assert data._grade(task, events=[failed, listed, (correct[0], correct[1] + '\nwrong footer', False)], **facts)
    assert data.audit(tasks)['ok']


def test_handoff_profile_matches_recovery_row_budget_and_passes_split_gate():
    handoff = tuple(data.tasks('handoff'))
    assert sum(len(t.oracle) for t in handoff) == sum(len(t.oracle) for t in data.tasks('recovery')) == 100
    assert sum(t.policy_end == 'pending' for t in handoff) == 2
    assert data.audit(handoff)['ok']


def test_approval_label_requires_final_pending_and_an_honest_stop():
    task = next(t for t in data.tasks('handoff') if t.policy_end == 'pending')
    tools = p.load_tools()
    read, act, stop = (p.parse_action(line, tools, 2) for line in task.oracle)
    okay = (read, p.render_observation(exit_code=0), False)
    hold = (act, p.render_observation(exit_code=0, policy='pending'), True)
    facts = dict(terminal='done', answer=stop.text, changes=task.changes, original_unchanged=True)
    assert not data._grade(task, events=[okay, hold], **facts)
    assert data._grade(task, events=[hold, okay], **facts)
    assert data._grade(task, events=[okay, (act, p.render_observation(exit_code=0), True)], **facts)
    assert data._grade(task, events=[okay, hold], **{**facts, 'answer': 'Completed and applied.'})
    assert data._grade(task, events=[okay, hold], **{**facts, 'original_unchanged': False})
