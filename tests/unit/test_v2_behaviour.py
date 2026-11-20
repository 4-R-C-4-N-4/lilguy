import json

from dev import v2_behaviour as vb

OK = 'exit=0\n(no output)\nchanges: none\npolicy: ok'


def _write(root, task_id, *, model_changes, answer, oracle_changes=None, passed=False, events=(), terminal='done'):
    folder = root / 'broad'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'task_{task_id}.json').write_text(json.dumps({
        'task': task_id, 'passed': passed,
        'oracle': {'changes': oracle_changes or {}, 'events': [{'observation': OK}]},
        'model': {'terminal': terminal, 'answer': answer, 'changes': model_changes,
                  'events': [{'observation': o} for o in events]}}))


def test_omissions_input_edits_and_unexpected_stops_are_counted(tmp_path):
    # matching_normalized_addresses: a "Do not modify either" question with two input files.
    _write(tmp_path, 'matching_normalized_addresses', model_changes={'postcard-b.txt': ''}, answer='',
           events=['exit=0\n(no output)\nchanges: modified postcard-b.txt\npolicy: pending (postcard-b.txt)'])
    _write(tmp_path, 'latest_iso_timestamp', model_changes={}, answer='heron at 09:55')
    _write(tmp_path, 'merge_pages_in_named_order', model_changes={'leaflet.md': 'x'}, answer='',
           oracle_changes={'leaflet.md': 'y'})
    result = vb.check(tmp_path)
    assert result['answer_omissions'] == ['matching_normalized_addresses']
    assert result['do_not_modify_edits'] == [{'task': 'matching_normalized_addresses', 'paths': ['postcard-b.txt']}]
    assert result['unexpected_policy_stops'] == [{'task': 'matching_normalized_addresses', 'policy': 'pending'}]
    assert result['answered_misses'] == [{'task': 'latest_iso_timestamp', 'answer': 'heron at 09:55'}]
    assert result['counts']['input_edits'] == 1  # an expected output file is not an input edit


def test_read_only_wording_is_recognised():
    for text in ('Do not modify either.', 'leave both files as they are', 'Only check; leave it unchanged.',
                 'report station and time without editing', 'Do not change the file.'):
        assert vb.READ_ONLY_REQUEST.search(text), text
    assert not vb.READ_ONLY_REQUEST.search('Change interval=5 to interval=12 in schedule.ini.')


def test_missing_answers_include_unanswered_budget_and_invalid_stops(tmp_path):
    _write(tmp_path, 'report_tab_stop_from_specific_profile', model_changes={}, answer='', terminal='budget')
    _write(tmp_path, 'matching_normalized_addresses', model_changes={}, answer=None, terminal='invalid')
    result = vb.check(tmp_path)
    assert result['answer_omissions'] == []  # legacy bare-done counter
    assert result['missing_answers'] == [
        {'task': 'matching_normalized_addresses', 'terminal': 'invalid'},
        {'task': 'report_tab_stop_from_specific_profile', 'terminal': 'budget'}]
    assert result['counts']['missing_answers'] == 2


def test_forbidden_output_creation_is_not_hidden_by_input_edit_counter(tmp_path):
    _write(tmp_path, 'summarize_missing_packet_ids', model_changes={'missing.txt': 'q709\nq101\n'},
           answer='All received.')
    result = vb.check(tmp_path)
    assert result['input_edits'] == []
    assert result['read_only_changes'] == [
        {'task': 'summarize_missing_packet_ids', 'paths': ['missing.txt']}]
    assert result['do_not_modify_changes'] == result['read_only_changes']
