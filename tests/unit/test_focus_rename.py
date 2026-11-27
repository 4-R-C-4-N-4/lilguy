"""The rename probe never overlaps a frozen held-out suite, and its fixture shape is sane.

20 tasks across four groups (spaces to dashes: 6, zero pad: 7, collisions (ask): 3, not a bulk
rename (twins): 4). Twins are near-misses where fs.rename is not the right tool; their oracle
(on both v6 and v8) is a scripted `mv`/`cp`, never `tool fs.rename`.
"""
import json
import tempfile
from pathlib import Path

from dev import eval_gate, focus_rename, holdout_runner


def test_probe_shape():
    assert len(focus_rename.TASKS) == 20
    assert len({t.id for t in focus_rename.TASKS}) == 20
    assert {name: len(tasks) for name, tasks in focus_rename.GROUPS.items()} == {
        'spaces to dashes': 6, 'zero pad': 7, 'collisions (ask)': 3,
        'not a bulk rename (twins)': 4,
    }
    assert sum(len(tasks) for tasks in focus_rename.GROUPS.values()) == 20
    assert focus_rename.ASK == {
        'collision_existing_target', 'collision_two_sources', 'collision_spaces_target_exists',
    }
    assert focus_rename.TWINS == {
        'twin_rename_single_file', 'twin_copy_with_dashes', 'twin_lowercase_names',
        'twin_strip_prefix',
    }
    for task in focus_rename.TASKS:
        # every task has both oracle variants: the module default is the v8 oracle, ORACLES_V6
        # the v6 replacement (identical to the default for twins, where fs.rename is never
        # the right tool on either version).
        assert task.oracle
        assert task.id in focus_rename.ORACLES_V6
        v6 = focus_rename.ORACLES_V6[task.id]
        assert v6
        if task.id in focus_rename.TWINS:
            assert not any('tool fs.rename' in line for line in task.oracle)
            assert v6 == task.oracle
        else:
            assert any('tool fs.rename' in line for line in task.oracle)
            assert not any('tool fs.rename' in line for line in v6)
        if task.terminal == 'ask':
            assert not any(line.startswith('run') for line in v6), "a collision oracle never mv's"


def test_group_membership_matches_ids():
    for name, tasks in focus_rename.GROUPS.items():
        ids = {t.id for t in tasks}
        if name == 'collisions (ask)':
            assert ids == focus_rename.ASK
        elif name == 'not a bulk rename (twins)':
            assert ids == focus_rename.TWINS
        else:
            assert not (ids & focus_rename.ASK) and not (ids & focus_rename.TWINS)


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
        elif task.id == 'twin_copy_with_dashes':
            # a copy stages only additions -- the originals are never deleted; the new
            # folder itself is one of the staged additions, alongside the copied files.
            assert not deleted
            assert added.pop('archive2') == '<dir added>'
            assert sorted(added.values()) == sorted(task.files.values())
        else:
            # every added file's content matches exactly one deleted file's content (a pure rename)
            deleted_contents = sorted(task.files[path] for path in deleted)
            assert sorted(added.values()) == deleted_contents


def test_non_twin_pending_tasks_are_pure_renames():
    """Every pending task outside the twins group has a changes dict that is a pure rename:
    the same multiset of file contents before and after, just deletes paired 1:1 with adds."""
    for task in focus_rename.TASKS:
        if task.terminal == 'ask' or task.id in focus_rename.TWINS:
            continue
        assert task.policy_end == 'pending'
        deleted = {path for path, text in task.changes.items() if text is None}
        deleted_contents = sorted(task.files[path] for path in deleted)
        added_contents = sorted(text for path, text in task.changes.items() if text is not None)
        assert deleted_contents == added_contents


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


def test_oracles_version_selection():
    assert focus_rename.oracles(6) == focus_rename.ORACLES_V6
    assert focus_rename.oracles(7) == focus_rename.ORACLES_V6
    assert focus_rename.oracles(8) == {}
    assert focus_rename.oracles(9) == {}
