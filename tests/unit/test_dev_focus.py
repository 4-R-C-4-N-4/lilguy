"""The v4 focus fixtures never overlap the frozen held-out suite or the 80-task roster."""
import json
from pathlib import Path

from dev import dev_focus
from dev.broad_runner import development_rows
from dev.split_audit import audit, parse_manifest

ROOT = Path(__file__).resolve().parents[2]


def test_focus_tasks_do_not_overlap_held_out_or_development():
    held = parse_manifest((ROOT / 'dev/holdout_manifest.json').read_text())
    rows = [dict(id=t.id, split='dev', template_id=t.id, request=t.request, files=t.files) for t in dev_focus.TASKS]
    focus = parse_manifest(json.dumps(rows))
    assert audit(held + focus).ok
    existing = {row['id'] for row in development_rows()}
    assert not existing & {t.id for t in dev_focus.TASKS}


def test_questions_have_v3_oracles_and_changes_have_none():
    assert set(dev_focus.ORACLES) == dev_focus.ASK == {t.id for t in dev_focus.QUESTIONS}
    assert all(t.changes for t in dev_focus.APPEND + dev_focus.REPEATED)
