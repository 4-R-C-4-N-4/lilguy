import json
import subprocess
import sys

import pytest

from dev.fast12 import TASKS


def result(root, winner, digest):
    root.mkdir()
    (root / 'identity.json').write_text(json.dumps(dict(evaluation_sha256=digest, gguf_sha256='c'*64)))
    rows = [dict(task=t.id, passed=i == winner, model_miss=i != winner, infra_failure=False)
            for i, t in enumerate(TASKS)]
    (root / 'fast12.json').write_text(json.dumps(dict(total=12, passed=1, model_misses=11,
                                                     infra_failures=0, tasks=rows)))


@pytest.mark.parametrize('case', ['clean', 'different', 'incomplete', 'infra'])
def test_compare_cli(tmp_path, case):
    a, b = tmp_path / 'stock', tmp_path / 'candidate'
    result(a, 0, 'a'*64)
    result(b, 1, ('b' if case == 'different' else 'a')*64)
    path = b / 'fast12.json'
    data = json.loads(path.read_text())
    if case == 'incomplete':
        data['tasks'].pop()
    if case == 'infra':
        data['tasks'][0]['infra_failure'] = True
    path.write_text(json.dumps(data))
    proc = subprocess.run([sys.executable, '-m', 'dev.factory', 'compare', '--stock', str(a),
                           '--candidate', str(b)], capture_output=True, text=True)
    if case == 'clean':
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert report['improved'] == [TASKS[1].id] and report['regressed'] == [TASKS[0].id]
    else:
        assert proc.returncode != 0 and 'improved' not in proc.stdout
