"""Held-out v4: frozen, pinned, registered, and gated against the full development roster."""
import json

from dev import holdout_runner, holdout_suite_v4
from dev import holdout_suite_v4_freeze as freeze


def test_v4_is_frozen_and_its_gate_covers_the_development_roster():
    holdout_runner.check_frozen('v4')
    result = holdout_runner.suite_gate('v4')
    assert result['ok'], result
    assert result['held_out_count'] == 100 and result['candidate_count'] == 106


def test_v4_roster_and_metadata():
    rows = json.loads((freeze.ROOT / 'dev/holdout_suite_v4_manifest.json').read_text())
    freeze.validate_roster(rows)
    meta = json.loads(freeze.META.read_text())
    assert meta['interface'] == 6 and meta['calibration'] == {'oracle_passed': 100, 'false_done_passed': 0,
                                                              'infra_failures': 0}
    assert holdout_runner.SUITES['v4']['interface'] == 6 and len(holdout_suite_v4.ASK) == 30


def test_v4_archive_grading_accepts_either_top_folder_layout():
    task = next(t for t in holdout_suite_v4.TASKS if t.id == 'heldout4_g_ringing')
    spec = holdout_suite_v4._EXPECTED[task.id]
    flat = {'ringing.tar.gz': holdout_suite_v4._archive('tar.gz', {'peal.txt': 'grandsire\n',
                                                                    'touch.txt': 'plain bob\n'})}
    events = [('tool', 'exit=0\nchanges: added ringing.tar.gz\npolicy: ok', False)]
    for changes in (spec.changes, flat):
        assert holdout_suite_v4.grade(task, terminal='done', answer='', changes=changes, events=events,
                                      original_unchanged=True) == []
