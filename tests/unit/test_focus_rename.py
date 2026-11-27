"""The rename probe never overlaps a frozen held-out suite, and its fixture shape is sane."""
import json
import tempfile
from pathlib import Path

from dev import eval_gate, focus_rename, holdout_runner


def test_probe_shape():
    assert len(focus_rename.TASKS) == 5
    assert len({t.id for t in focus_rename.TASKS}) == 5
    assert focus_rename.ASK == {'collision_existing_target', 'collision_two_sources'}
    for task in focus_rename.TASKS:
        # both oracle variants exist: the module default is the v8 oracle, ORACLES_V6 the v6 one.
        assert task.oracle and any('tool fs.rename' in line for line in task.oracle)
        assert task.id in focus_rename.ORACLES_V6
        v6 = focus_rename.ORACLES_V6[task.id]
        assert v6 and not any('tool fs.rename' in line for line in v6)
        if task.terminal == 'ask':
            assert not any(line.startswith('run') for line in v6), "a collision oracle never mv's"


def test_expected_effects_consistent_with_files():
    for task in focus_rename.TASKS:
        deleted = {path for path, text in task.changes.items() if text is None}
        added = {path: text for path, text in task.changes.items() if text is not None}
        # every deletion must be a real input file, and no added path collides with a surviving one
        assert deleted <= set(task.files)
        surviving = set(task.files) - deleted
        assert not (surviving & set(added)), (task.id, 'added path collides with a kept file')
        if task.terminal == 'ask':
            assert task.changes == {}, 'a refused rename must stage nothing'
        else:
            # every added file's content matches exactly one deleted file's content (a pure rename)
            deleted_contents = sorted(task.files[path] for path in deleted)
            assert sorted(added.values()) == deleted_contents


def test_probe_does_not_overlap_any_frozen_held_out_suite():
    rows = [dict(id=t.id, split='dev', template_id=t.id, request=t.request, files=t.files)
            for t in focus_rename.TASKS]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'probe.json'
        path.write_text(json.dumps(rows))
        for suite in ('v2', 'v3', 'v4'):
            spec = holdout_runner.SUITES[suite]
            pin = (holdout_runner.ROOT / spec['pin']).read_text().split()[0]
            result = eval_gate.verify(holdout_runner.ROOT / spec['manifest'], pin, path)
            assert result['ok'], (suite, result)
