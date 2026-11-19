from dev import dev_verification as suite
from lilguy import protocol


def test_noop_requires_observed_value_and_no_intermediate_writes():
    task = next(t for t in suite.TASKS if t.id == 'leave_matching_output_style')
    read = protocol.Action.call('fs.read', path='display.ini')
    good = (read, protocol.render_observation(exit_code=0, stdout='output_style=compact'), False)
    unrelated = (read, protocol.render_observation(exit_code=0, stdout='theme=pine'), False)
    changed = (read, protocol.render_observation(exit_code=0, changes=[('modified', 'display.ini')]), False)
    facts = dict(terminal='done', answer='Already compact; no change needed.', changes={}, original_unchanged=True)
    assert not suite.grade(task, events=[good], **facts)
    assert suite.grade(task, events=[unrelated], **facts)
    assert suite.grade(task, events=[changed, good], **facts)
    assert suite.grade(task, events=[good], **{**facts, 'answer': 'Changed it to compact.'})


def test_successful_stdout_is_required_not_error_text_or_an_unrelated_success():
    task = next(t for t in suite.TASKS if t.id == 'recover_export_owner_lookup')
    read = protocol.Action.call('fs.read', path='owners/last-known.txt')
    good = (read, protocol.render_observation(exit_code=0, stdout='duty_owner: Mira Vale'), False)
    bad = (read, protocol.render_observation(exit_code=1, stderr='duty_owner: Mira Vale'), True)
    unrelated = (read, protocol.render_observation(exit_code=0, stdout='unrelated settings'), False)
    facts = dict(terminal='done', answer='The owner is Mira Vale.', changes={}, original_unchanged=True)
    assert not suite.grade(task, events=[bad, good], **facts)
    assert suite.grade(task, events=[bad, unrelated], **facts)
    assert suite.grade(task, events=[good, bad], **facts)


def test_numeric_evidence_is_stdout_content_not_its_line_count():
    task = next(t for t in suite.TASKS if t.id == 'report_tab_stop_from_specific_profile')
    read = protocol.Action.call('fs.read', path='format.conf')
    arbitrary = (read, protocol.render_observation(exit_code=0, stdout='[print]\na\nb\nc\nd\ne'), False)
    facts = dict(terminal='done', answer='The print tab stop is 6.', changes={}, original_unchanged=True)
    assert suite.grade(task, events=[arbitrary], **facts)
