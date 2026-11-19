from dev import factory


def test_skips_are_not_evidence(tmp_path):
    report = tmp_path / 'tests.xml'
    report.write_text('<testsuites><testsuite><testcase><skipped/></testcase></testsuite></testsuites>')
    assert not factory.all_executed(report)
    report.write_text('<testsuites><testsuite><testcase/></testsuite></testsuites>')
    assert factory.all_executed(report)


def test_evaluation_gate_uses_real_suites_and_stops_on_bad_pin(tmp_path):
    assert factory.evaluation_gate()['ok']
    pin = tmp_path / 'pin'
    pin.write_text('0' * 64 + '\n')
    assert factory.evaluation_gate(pin_path=pin) == {'ok': False, 'reason': 'held-out digest mismatch'}


def test_model_job_refuses_before_launch_when_gate_fails(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(factory, 'evaluation_gate', lambda: {'ok': False, 'reason': 'held-out digest mismatch'})
    model = tmp_path / 'm.gguf'
    model.write_bytes(b'x')
    monkeypatch.setattr('sys.argv', ['factory', 'fast12', '--gguf', str(model), '--server', str(model)])
    with pytest.raises(SystemExit) as exc:
        factory.main()
    assert exc.value.code == 1


def test_failed_stage_stops_job(tmp_path):
    import sys
    import json
    result = factory.execute(tmp_path, [('bad', [sys.executable, '-c', 'raise SystemExit(4)'], None),
                                        ('later', [], None)])
    assert result != 0
    manifest = json.loads((tmp_path / 'result.json').read_text())
    assert manifest['status'] == 'failed'
    assert [s['name'] for s in manifest['stages']] == ['bad']
