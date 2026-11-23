"""Round-11 focus fixtures: no overlap with any frozen held-out suite, the roster or the v4 focus set."""
import json
from pathlib import Path

from dev import dev_focus, focus_r11
from dev.broad_runner import development_rows
from dev.split_audit import audit, parse_manifest

ROOT = Path(__file__).resolve().parents[2]


def test_no_overlap_with_held_out_suites_roster_or_v4_focus():
    rows = []
    for i, name in enumerate(('holdout_manifest.json', 'holdout_v2_manifest.json', 'holdout_suite_v3_manifest.json')):
        rows += [dict(r, id=f'h{i}-{r["id"]}', split='held-out') for r in json.loads((ROOT / 'dev' / name).read_text())]
    rows += [dict(r, split='dev') for r in development_rows()]
    rows += [dict(id=t.id, split='dev', template_id=t.id, request=t.request, files=t.files) for t in dev_focus.TASKS]
    focus = [dict(id='r11-' + t.id, split='dev', template_id='r11-' + t.id, request=t.request, files=t.files)
             for t in focus_r11.TASKS]
    findings = [r for r in audit(parse_manifest(json.dumps(rows + focus))).reasons if 'r11-' in r]
    assert findings == []


def test_shape():
    assert len(focus_r11.TASKS) == 25 and len({t.id for t in focus_r11.TASKS}) == 25
    assert set(focus_r11.ORACLES) == focus_r11.ASK == {t.id for t in focus_r11.QUOTE + focus_r11.COUNT}
    assert all(t.changes for t in focus_r11.CREATE + focus_r11.NO_EOL)
    assert all(t.terminal == 'ask' and not t.changes for t in focus_r11.MISSING)
