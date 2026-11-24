"""Freeze integrity and successor-suite integration (no model)."""
import hashlib
import json

import pytest

from dev import factory, holdout_runner
from dev import holdout_suite_v3_freeze as freeze


def test_v3_selected_gate_covers_the_full_development_roster():
    result = holdout_runner.suite_gate('v3')
    assert result['ok'], result
    assert result['held_out_count'] == 100 and result['candidate_count'] == 106


def test_missing_or_duplicate_roster_fails_even_if_re_pinned():
    rows = freeze.held_rows()
    freeze.validate_roster(rows)
    for broken in (rows[:-1], rows[:-1] + rows[:1]):
        with pytest.raises(ValueError, match='100 distinct'):
            freeze.validate_roster(broken)


def test_changed_manifest_bytes_are_rejected(tmp_path, monkeypatch):
    path = tmp_path / 'manifest.json'
    path.write_bytes(freeze.MANIFEST.read_bytes() + b' ')
    monkeypatch.setitem(holdout_runner.SUITES['v3'], 'manifest', str(path))
    with pytest.raises(ValueError, match='does not match its pin'):
        holdout_runner.check_frozen('v3')


def test_changed_expected_effect_cannot_hide_behind_same_request_and_files(tmp_path, monkeypatch):
    rows = json.loads(freeze.MANIFEST.read_text())
    rows[0]['expected']['changes'] = {'wrong-file.txt': 'wrong effect\n'}
    path, pin = tmp_path / 'manifest.json', tmp_path / 'pin'
    path.write_text(json.dumps(rows))
    pin.write_text(hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setitem(holdout_runner.SUITES['v3'], 'manifest', str(path))
    monkeypatch.setitem(holdout_runner.SUITES['v3'], 'pin', str(pin))
    with pytest.raises(ValueError, match='expectations differ'):
        holdout_runner.check_frozen('v3')


def test_source_change_is_rejected(tmp_path, monkeypatch):
    meta = json.loads(freeze.META.read_text())
    source = tmp_path / 'changed.py'
    source.write_text('# changed grading code\n')
    original_root = holdout_runner.ROOT

    class RedirectRoot:
        def __truediv__(self, name):
            if name == next(iter(meta['source_sha256'])):
                return source
            return original_root / name

    monkeypatch.setattr(holdout_runner, 'ROOT', RedirectRoot())
    with pytest.raises(ValueError, match='frozen source changed'):
        holdout_runner.check_frozen('v3')


def test_repeat_guard_keys_v3_independently(tmp_path):
    run = tmp_path / 'held-out-previous'
    run.mkdir()
    (run / 'identity.json').write_text(json.dumps({'gguf_sha256': 'model', 'held_out_suite': 'v2'}))
    assert factory.previous_held_out('model', tmp_path, suite='v3') == []
    (run / 'identity.json').write_text(json.dumps({'gguf_sha256': 'model', 'held_out_suite': 'v3'}))
    assert factory.previous_held_out('model', tmp_path, suite='v3') == [run]


def test_freezer_rejects_incomplete_or_skipped_calibration(tmp_path):
    path = tmp_path / 'controls.xml'
    path.write_text('<testsuites><testsuite><testcase name="unrelated"/></testsuite></testsuites>')
    with pytest.raises(ValueError, match='all 100'):
        freeze.check_calibration(path)
