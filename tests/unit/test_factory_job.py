import xml.etree.ElementTree as ET

from dev import factory


def test_skips_are_not_evidence(tmp_path):
    report = tmp_path / 'tests.xml'
    report.write_text('<testsuites><testsuite><testcase><skipped/></testcase></testsuite></testsuites>')
    assert not factory.all_executed(report)
    report.write_text('<testsuites><testsuite><testcase/></testsuite></testsuites>')
    assert factory.all_executed(report)


def test_full_safety_evidence_rejects_a_deselected_or_substituted_case(tmp_path):
    path = tmp_path / 'safety.xml'
    expected = frozenset({('tests.safety', 'case[other]'), ('tests.safety', 'case[required]')})

    def save(roster):
        suite = ET.Element('testsuite')
        for name in roster:
            ET.SubElement(suite, 'testcase', classname='tests.safety', name=name)
        ET.ElementTree(suite).write(path)

    save(['case[other]'])
    assert not factory.all_executed(path, required=expected)
    save(['case[other]', 'case[other]'])
    assert not factory.all_executed(path, required=expected)
    save(['case[other]', 'case[unrelated]'])
    assert not factory.all_executed(path, required=expected)
    save(['case[other]', 'case[required]'])
    assert factory.all_executed(path, required=expected)


def test_check_cannot_silently_deselect_the_missing_dependency_case(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['factory', 'check'])
    captured = {}

    def execute(directory, stages, *, required_cases):
        captured.update(suite=stages, cases=required_cases)
        return 0

    monkeypatch.setattr(factory, 'execute', execute)
    assert factory.main() == 0
    names = [stage[0] for stage in captured['suite']]
    assert names.index('safety-prerequisites') < names.index('v1-bypass-corpus')
    corpus = next(argv for name, argv, _ in captured['suite'] if name == 'v1-bypass-corpus')
    assert '--deselect' not in corpus
    assert ('tests.bypass.test_v1_run_corpus', 'test_corpus_through_v1_run_never_commits[17]') in (
        captured['cases']['v1-bypass-corpus'])


def test_evaluation_gate_uses_real_suites_and_stops_on_bad_pin(tmp_path):
    result = factory.evaluation_gate()
    assert result['ok']
    assert result['candidate_count'] == 106
    assert result['held_out_count'] == 100
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


def test_cli_parser_builds_and_margins_needs_a_pilot():
    import subprocess
    import sys
    ok = subprocess.run([sys.executable, '-m', 'dev.factory', '--help'], capture_output=True, text=True)
    assert ok.returncode == 0 and 'margins' in ok.stdout
    bad = subprocess.run([sys.executable, '-m', 'dev.factory', 'margins'], capture_output=True, text=True)
    assert bad.returncode != 0 and '--pilot' in bad.stderr
