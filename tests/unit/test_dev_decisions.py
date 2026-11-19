import pytest

from dev import dev_decisions as dev
from lilguy import protocol as p


@pytest.mark.parametrize('task_id,good,bad', [
    ('matching_normalized_addresses', 'The two files match after normalization.',
     'No, the files do not match after normalization.'),
    ('no_marker_in_schedule', 'No row starts with CANCELLED.',
     'Yes, a row starts with CANCELLED, but no files were changed.'),
])
def test_read_grader_does_not_accept_the_opposite_answer(task_id, good, bad):
    task = next(t for t in dev.TASKS if t.id == task_id)
    response = p.render_observation(exit_code=0)
    kwargs = dict(terminal='done', changes={}, original_unchanged=True,
                  events=[(p.Action.run('true'), response, False)])
    assert not dev.grade(task, answer=good, **kwargs)
    assert dev.grade(task, answer=bad, **kwargs)
