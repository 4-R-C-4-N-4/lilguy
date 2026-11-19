"""Broader development model job: separate identity and complete fixture roster."""
import json
from pathlib import Path

from dev import broad_dev, broad_runner, dev_shell, factory, fast12


def test_broad_identity_hashes_extra_sources_without_changing_fast12(tmp_path):
    model = tmp_path / 'model.gguf'
    server = tmp_path / 'server'
    model.write_bytes(b'candidate')
    server.write_bytes(b'server')
    daily = factory.fast12_identity(model, server)
    broad = factory.fast12_identity(model, server, extra_sources=broad_runner.SOURCES)
    assert broad['gguf_sha256'] == daily['gguf_sha256']
    assert broad['evaluation_sha256'] != daily['evaluation_sha256']
    assert set(broad['evaluation_inputs']) - set(daily['evaluation_inputs']) == set(broad_runner.SOURCES)


def test_broad_roster_has_every_non_fast12_development_task_once():
    from dev import dev_decisions, dev_text_workflows, dev_verification, dev_workspace
    selected = list(broad_runner.task_graders())
    expected = {t.id: broad_dev.grade for t in broad_dev.TASKS}
    expected.update({t.id: dev_shell.grade for t in dev_shell.TASKS})
    expected.update({t.id: dev_decisions.grade for t in dev_decisions.TASKS})
    expected.update({t.id: dev_verification.grade for t in dev_verification.TASKS})
    expected.update({t.id: dev_workspace.grade for t in dev_workspace.TASKS})
    expected.update({t.id: dev_text_workflows.grade for t in dev_text_workflows.TASKS})
    assert len(selected) == len(expected) == 68
    assert {task.id: grade for task, grade in selected} == expected
    assert expected.keys().isdisjoint(t.id for t in fast12.TASKS)


def test_failed_split_gate_stops_broad_job_before_preflight(tmp_path, monkeypatch):
    import pytest
    model = tmp_path / 'model.gguf'
    model.touch()
    monkeypatch.setattr(factory, 'evaluation_gate', lambda: {'ok': False, 'reason': 'digest mismatch'})
    monkeypatch.setattr('sys.argv', ['factory', 'broad', '--gguf', str(model), '--server', str(model)])
    with pytest.raises(SystemExit) as exc:
        factory.main()
    assert exc.value.code == 1


def test_summary_records_changed_original_as_failure_even_with_passing_grader(tmp_path):
    verdict = dict(task='one', passed=True, infra_failure=False, model_miss=False,
                   model={'terminal': 'done', 'original_unchanged': False, 'metrics': None})
    assert broad_runner.write_summary(tmp_path, [verdict]) != 0
    summary = json.loads((Path(tmp_path) / 'broad.json').read_text())
    assert summary['originals_changed'] == 1
    assert summary['passed'] == 0
