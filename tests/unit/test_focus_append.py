"""The append probe never overlaps a frozen held-out suite or the development roster."""
import json
import tempfile
from pathlib import Path

from dev import broad_runner, dev_focus, eval_gate, focus_append, focus_r11, holdout_runner


def test_probe_shape():
    assert len(focus_append.TASKS) == 20 and len({t.id for t in focus_append.TASKS}) == 20
    assert sum(not next(iter(t.files.values())).endswith('\n') for t in focus_append.TASKS) == 10


def dev_rows(tasks):
    return [dict(id=t.id, split='dev', template_id=t.id, request=t.request, files=t.files) for t in tasks]


def test_probe_does_not_overlap_the_roster_or_earlier_focus_sets():
    from dev import split_audit

    rows = broad_runner.development_rows() + dev_rows((*dev_focus.TASKS, *focus_r11.TASKS, *focus_append.TASKS))
    findings = split_audit.audit(split_audit.parse_manifest(json.dumps(rows))).reasons
    assert not [reason for reason in findings if 'append_probe_' in reason]


def test_probe_does_not_overlap_any_frozen_held_out_suite():
    rows = dev_rows(focus_append.TASKS)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'probe.json'
        path.write_text(json.dumps(rows))
        for suite in holdout_runner.SUITES:
            spec = holdout_runner.SUITES[suite]
            pin = (holdout_runner.ROOT / spec['pin']).read_text().split()[0]
            result = eval_gate.verify(holdout_runner.ROOT / spec['manifest'], pin, path)
            assert result['ok'], (suite, result)
