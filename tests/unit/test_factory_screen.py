import hashlib
import json

import pytest

from dev import broad_runner, factory, fast12


def test_screen_compares_complete_fixtures_even_when_models_miss(tmp_path, monkeypatch):
    root = tmp_path / 'reports' / 'factory'
    roster = {'fast12': fast12.TASKS, 'broad': tuple(t for t, _ in broad_runner.task_graders())}
    model_paths = [tmp_path / name for name in ('small.gguf', 'large.gguf')]
    for path in model_paths:
        path.write_bytes(path.name.encode())
    monkeypatch.setattr(factory, 'ROOT', tmp_path)
    monkeypatch.setattr(factory, 'evaluation_gate', lambda: {'ok': True})
    monkeypatch.setattr(factory, 'gpu_device', lambda *_: 'RTX 3090')
    monkeypatch.setattr('sys.argv', ['factory', 'screen', '--server', str(model_paths[0]),
                                   '--model', f'small={model_paths[0]}', '--model', f'large={model_paths[1]}',
                                   '--reference', 'large'])

    calls = []

    def run(directory, suite, gguf, server, device):
        assert (root / '.lock').is_file()
        calls.append((gguf, suite))
        large = gguf == model_paths[1]
        gguf_hash = hashlib.sha256(gguf.read_bytes()).hexdigest()
        (directory / 'identity.json').write_text(json.dumps(dict(
            device=device, evaluation_sha256=hashlib.sha256(suite.encode()).hexdigest(),
            gguf_sha256=gguf_hash)))
        rows = []
        for i, task in enumerate(roster[suite]):
            passed = i == int(large)
            model = dict(original_unchanged=True, infra_error=None, terminal='done', events=[],
                         metrics=dict(episode_seconds=2.0 if large else 1.0, model_seconds=0.4))
            rows.append(dict(task=task.id, passed=passed, infra_failure=False,
                             terminal=model['terminal'], metrics=model['metrics']))
            (directory / f'task_{task.id}.json').write_text(json.dumps(dict(
                task=task.id, model=model, passed=passed, infra_failure=False, controls_agree=True)))
        (directory / f'{suite}.json').write_text(json.dumps(dict(
            total=len(rows), passed=1, infra_failures=0, tasks=rows)))
        (directory / 'result.json').write_text(json.dumps(dict(stages=[dict(exit=1)])))
        return 1  # evaluation job rc for task misses, not an infrastructure failure

    monkeypatch.setattr(factory, 'run_development', run, raising=False)
    assert factory.main() == 0
    assert calls == [(model, suite) for model in model_paths for suite in ('fast12', 'broad')]
    report_path, = root.glob('screen-*/comparison.json')
    result = json.loads(report_path.read_text())
    assert result['reference'] == 'large'
    small = result['models']['small']
    assert small['completed'] == 2
    for suite, tasks in roster.items():
        measured = small['suites'][suite]
        assert measured['only_model'] == [tasks[0].id]
        assert measured['only_reference'] == [tasks[1].id]
        assert measured['episode_ratio_to_reference'] == 0.5
        assert measured['clarification_total'] == 0  # interface v2: no ask tasks on the model roster


@pytest.mark.parametrize('labels,error', [(['small', 'small'], 'duplicate'), (['../small', 'large'], 'label')])
def test_screen_rejects_unsafe_or_duplicate_labels_before_gpu(tmp_path, monkeypatch, capsys, labels, error):
    model = tmp_path / 'model.gguf'
    model.touch()
    monkeypatch.setattr(factory, 'gpu_device', lambda *_: pytest.fail('must reject before GPU preflight'))
    monkeypatch.setattr('sys.argv', ['factory', 'screen', '--server', str(model), '--reference', labels[-1],
                                   '--model', f'{labels[0]}={model}', '--model', f'{labels[1]}={model}'])
    with pytest.raises(SystemExit) as exc:
        factory.main()
    assert exc.value.code == 2
    assert error in capsys.readouterr().err
