import json

from dev import baseline_report


def run(root, name, passes, terminals, seconds, events=()):
    d = root / name
    d.mkdir()
    (d / 'identity.json').write_text(json.dumps(dict(device='GPU', evaluation_sha256='e' * 64, gguf_sha256='g' * 64)))
    tasks = []
    for i, (ok, terminal) in enumerate(zip(passes, terminals)):
        tasks.append(dict(task=f't{i}', passed=ok, infra_failure=False, model_miss=not ok, terminal=terminal,
                          metrics=dict(requests=2, prompt_tokens=100, completion_tokens=10,
                                       model_seconds=seconds, episode_seconds=seconds + 1)))
        (d / f'task_t{i}.json').write_text(json.dumps(dict(model=dict(events=list(events) if i == 0 else []))))
    (d / 'fast12.json').write_text(json.dumps(dict(total=len(tasks), passed=sum(passes), infra_failures=0,
                                                   model_misses=len(tasks) - sum(passes), tasks=tasks)))
    return d


def test_summary_counts_failures_and_safety_signals(tmp_path):
    events = [dict(observation='exit=1\npolicy: ok', is_error=True),
              dict(observation='exit=0\nchanges: deleted a\npolicy: pending (rule)', is_error=True)]
    d = run(tmp_path, 'a', [True, False, False, False], ['done', 'invalid', 'done', 'ask'], 0.5, events)
    s = baseline_report.summarize(d)
    assert (s['passed'], s['total'], s['invalid'], s['policy_stops']) == (1, 4, 1, 1)
    assert s['false_done'] == 1          # t2 said done without passing
    assert 0 < s['ci_low'] < 0.25 < s['ci_high'] < 1
    assert s['median_model_seconds'] == 0.5 and s['device'] == 'GPU'


def test_markdown_refuses_mixed_harness(tmp_path):
    a = run(tmp_path, 'a', [True], ['done'], 1.0)
    b = run(tmp_path, 'b', [False], ['ask'], 2.0)
    ident = json.loads((b / 'identity.json').read_text())
    ident['evaluation_sha256'] = 'f' * 64
    (b / 'identity.json').write_text(json.dumps(ident))
    try:
        baseline_report.markdown([('a', a), ('b', b)], references=[])
    except ValueError as exc:
        assert 'evaluation' in str(exc)
    else:
        raise AssertionError('mixed evaluation fingerprints must not be tabulated together')


def test_markdown_reports_latency_ratio_per_reference(tmp_path):
    small = run(tmp_path, 'small', [True], ['done'], 1.0)
    big = run(tmp_path, 'big', [True], ['done'], 20.0)
    text = baseline_report.markdown([('small', small), ('big', big)], references=['big'])
    assert '| small |' in text and '5.0%' in text
