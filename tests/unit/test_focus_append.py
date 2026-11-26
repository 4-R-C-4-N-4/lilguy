"""The append probe never overlaps a frozen held-out suite or the development roster."""
import json
import tempfile
from pathlib import Path

from dev import eval_gate, focus_append, holdout_runner


def test_probe_shape():
    assert len(focus_append.TASKS) == 20 and len({t.id for t in focus_append.TASKS}) == 20
    assert sum(not next(iter(t.files.values())).endswith('\n') for t in focus_append.TASKS) == 10


def test_probe_does_not_overlap_any_frozen_held_out_suite():
    rows = [dict(id=t.id, split='dev', template_id=t.id, request=t.request, files=t.files)
            for t in focus_append.TASKS]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'probe.json'
        path.write_text(json.dumps(rows))
        for suite in ('v2', 'v3', 'v4'):
            spec = holdout_runner.SUITES[suite]
            pin = (holdout_runner.ROOT / spec['pin']).read_text().split()[0]
            result = eval_gate.verify(holdout_runner.ROOT / spec['manifest'], pin, path)
            assert result['ok'], (suite, result)
