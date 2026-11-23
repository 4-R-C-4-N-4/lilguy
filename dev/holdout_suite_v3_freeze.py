"""Freeze successor held-out suite v3 after live controls; never runs a model.

Run the 100 sandbox controls with --junitxml=PATH, then:
    .venv/bin/python -m dev.holdout_suite_v3_freeze --calibration PATH

Audit all corpus revisions 1..10, development/focus fixtures, and held-out v1/v2.
The audit is structural, not a semantic paraphrase detector.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from dev import dev_focus, holdout_suite_v3, split_audit, v2_corpus
from dev.broad_runner import development_rows

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'dev/holdout_suite_v3_manifest.json'
DIGEST = ROOT / 'dev/holdout_suite_v3_manifest.sha256'
META = ROOT / 'dev/holdout_suite_v3_manifest.meta.json'
# Include grading dependencies, not just request/fixture bytes.
SOURCES = ('dev/holdout_suite_v3.py', 'dev/holdout_corpus.py',
           'tests/sandbox/test_holdout_suite_v3_controls_live.py')


def held_rows():
    return [dict(id=t.id, split='held-out', template_id=f'heldout3-{t.id.split("_")[1]}',
                 request=t.request, files=t.files, oracle=t.oracle,
                 mode='ask' if t.id in holdout_suite_v3.ASK else 'do',
                 expected=asdict(holdout_suite_v3._EXPECTED[t.id]))
            for t in holdout_suite_v3.TASKS]


def other_rows():
    rows = [dict(r, split='dev') for r in development_rows()]
    rows += [dict(id=t.id, split='dev', template_id=t.id, request=t.request, files=t.files)
             for t in dev_focus.TASKS]
    for suite, name in (('v1', 'holdout_manifest.json'), ('v2', 'holdout_v2_manifest.json')):
        rows += [dict(r, split='dev', id=f'{suite}-{r["id"]}')
                 for r in json.loads((ROOT / 'dev' / name).read_text())]
    for revision in range(1, 11):
        rows += [dict(ex.manifest(), id=f'r{revision}-{ex.id}')
                 for ex in v2_corpus.generate(revision=revision)]
    return rows


def validate_roster(rows):
    counts = Counter(r['id'].split('_')[1] for r in rows)
    if len(rows) != 100 or len({r['id'] for r in rows}) != 100 \
            or counts != {key: 10 for key in holdout_suite_v3.FAMILIES}:
        raise ValueError('expected exactly 100 distinct tasks, 10 per declared family')


def check_calibration(path):
    cases = ET.parse(path).getroot().findall('.//testcase')
    expected = {f'test_holdout_suite_v3_controls[{t.id}]' for t in holdout_suite_v3.TASKS}
    if len(cases) != 100 or {c.get('name') for c in cases} != expected \
            or any(c.find(tag) is not None for c in cases for tag in ('skipped', 'failure', 'error')):
        raise ValueError('calibration must execute all 100 live control tests without skips or failures')
    if any((ROOT / src).stat().st_mtime_ns > path.stat().st_mtime_ns for src in SOURCES):
        raise ValueError('calibration predates a suite/control source change; recalibrate')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibration', required=True, type=Path)
    args = parser.parse_args(argv)
    check_calibration(args.calibration)
    held = held_rows()
    validate_roster(held)
    others = other_rows()
    entries = split_audit.parse_manifest(json.dumps(held + others))
    findings = [r for r in split_audit.audit(entries).reasons if 'heldout3_' in r]
    if findings:
        raise ValueError('overlap audit failed:\n' + '\n'.join(findings))
    data = (json.dumps(held, indent=2, sort_keys=True) + '\n').encode()
    digest = hashlib.sha256(data).hexdigest()
    if MANIFEST.exists() and MANIFEST.read_bytes() != data:
        raise ValueError('refusing to replace an existing freeze with different tasks')
    meta = dict(held_out_count=100, audited_against=len(others), manifest_sha256=digest,
                families=dict(sorted(Counter(r['template_id'] for r in held).items())),
                ask_mode=len(holdout_suite_v3.ASK), interface=4,
                source_sha256={s: hashlib.sha256((ROOT / s).read_bytes()).hexdigest() for s in SOURCES},
                calibration_sha256=hashlib.sha256(args.calibration.read_bytes()).hexdigest(),
                calibration={'oracle_passed': 100, 'false_done_passed': 0, 'infra_failures': 0},
                note='Frozen before any model run; run once per model bytes and suite; no tuning on results.',
                audit_limits='Exact requests/fixtures and shallow normalized pairs; not semantic paraphrase detection.')
    MANIFEST.write_bytes(data)
    DIGEST.write_text(f'{digest}  dev/holdout_suite_v3_manifest.json\n')
    META.write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    print(json.dumps(meta, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
