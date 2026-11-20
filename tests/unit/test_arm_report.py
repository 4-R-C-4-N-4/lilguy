from dev import arm_report


def _verdict(terminal, passed, answer='q?', changes=None):
    return {'passed': passed, 'model': {'terminal': terminal, 'answer': answer, 'changes': changes or {}}}


def test_clarification_outcomes_separate_relevant_irrelevant_and_acting():
    assert arm_report.clarification_outcome(_verdict('ask', True)) == 'relevant ask'
    assert arm_report.clarification_outcome(_verdict('ask', False)) == 'irrelevant ask'
    assert arm_report.clarification_outcome(_verdict('done', False, changes={'a': 'x'})) == 'acted with changes'
    assert arm_report.clarification_outcome(_verdict('done', False)) == 'done without asking'
    assert arm_report.clarification_outcome(_verdict('budget', False, answer='')) == 'budget'
