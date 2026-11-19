#!/usr/bin/env python3
"""Freeze the independently authored held-out corpus (dev/holdout_corpus.py) into a pinned
manifest + digest, after running every offline validation this repo already has available
(dev/split_audit.py's leak checks, plus this module's own structural/grading checks).

Deliberately separate from dev/factory.py and dev/eval_gate.py: this script computes and writes
the pin itself, from the frozen file's own bytes, so the evaluation job that later *consumes*
the pin (via `dev.factory audit-splits` / `dev.eval_gate.verify`) can never be the thing that
derives it. Neither dev/factory.py nor dev/eval_gate.py is imported or modified here except as a
read-only dependency (dev/split_audit.py).

No model calls, no training, no shell execution, no network access. Running this script with no
arguments re-validates and (re)writes:
  dev/holdout_manifest.json   -- frozen candidate held-out manifest (>=100 entries, split='held-out')
  dev/holdout_manifest.sha256 -- sha256 of the manifest file's exact bytes, pinned independently
  dev/holdout_manifest.meta.json -- non-secret provenance (counts, family breakdown, digest)

Refuses to write anything (exit 1) if any validation fails.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dev import holdout_corpus as hc           # noqa: E402  (new, dev-only module)
from dev import fast12, broad_dev              # noqa: E402  (existing dev suites, read-only)
from dev import split_audit as sa              # noqa: E402  (existing auditor, read-only)

MANIFEST_PATH = ROOT / "dev" / "holdout_manifest.json"
DIGEST_PATH = ROOT / "dev" / "holdout_manifest.sha256"
META_PATH = ROOT / "dev" / "holdout_manifest.meta.json"


def _family(task_id: str) -> str:
    # "holdout_<letter>_..." -> "<letter>"; used only as a non-identifying grouping key.
    parts = task_id.split("_")
    return parts[1] if len(parts) > 1 and parts[0] == "holdout" else "unknown"


def _entry(task, split: str) -> dict:
    return {
        "id": task.id,
        "split": split,
        "template_id": f"holdout-{_family(task.id)}" if split == "held-out" else f"dev-{task.id}",
        "request": task.request,
        "files": dict(task.files),
    }


def build_candidate_entries() -> list:
    """The current dev-split corpus the held-out set must never overlap/leak against."""
    return [_entry(t, "dev") for t in (*fast12.TASKS, *broad_dev.TASKS)]


def build_held_out_entries() -> list:
    return [_entry(t, "held-out") for t in hc.TASKS]


def validate(held_entries: list, dev_entries: list) -> list:
    """Returns a list of human-readable failure reasons; empty means validation passed.
    Never includes raw request/file text -- only counts, ids and dev/split_audit's own reasons
    (which are themselves id-only by contract)."""
    reasons = []

    if len(held_entries) < 100:
        reasons.append(f"only {len(held_entries)} held-out tasks, need at least 100")

    ids = [e["id"] for e in held_entries]
    if len(set(ids)) != len(ids):
        reasons.append("duplicate ids within the held-out set")

    families = {_family(t.id) for t in hc.TASKS}
    if len(families) < 5:
        reasons.append(f"only {len(families)} distinct template families, want real diversity")

    for t in hc.TASKS:
        if t.id not in hc._EXPECTED:
            reasons.append(f"task {t.id} has no registered grading spec")

    # Pure-structural overlap/duplication audit, reused unmodified from dev/split_audit.py.
    # Only cross-split reasons (a held-out id mixed with a dev id) are a real leak here: dev's
    # own fast12 suite intentionally shares a request/fixture across two of *its own* same-split
    # entries (see dev/split_audit.py's module docstring), which is not this script's concern.
    try:
        all_rows = [sa.Entry(**e) for e in (*held_entries, *dev_entries)]
    except TypeError as exc:
        reasons.append(f"malformed entry shape for split_audit: {exc}")
        return reasons
    held_ids = {e["id"] for e in held_entries}
    dev_ids = {e["id"] for e in dev_entries}
    report = sa.audit(all_rows)
    cross = [r for r in report.reasons
             if any(i in r for i in held_ids) and any(i in r for i in dev_ids)]
    reasons.extend(f"split_audit(cross-split): {r}" for r in cross)

    # held-out-only self-audit too (catches internal near-duplicates even if dev is empty/changes)
    held_only_report = sa.audit([sa.Entry(**e) for e in held_entries])
    if not held_only_report.ok:
        reasons.extend(f"split_audit(held-out only): {r}" for r in held_only_report.reasons)

    return reasons


def main() -> int:
    held_entries = build_held_out_entries()
    dev_entries = build_candidate_entries()
    reasons = validate(held_entries, dev_entries)
    if reasons:
        print(json.dumps({"ok": False, "reasons": reasons}, indent=2))
        return 1

    manifest_text = json.dumps(held_entries, indent=2, sort_keys=True) + "\n"
    MANIFEST_PATH.write_text(manifest_text, encoding="utf8")
    digest = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    DIGEST_PATH.write_text(digest + "\n", encoding="utf8")

    family_counts = {}
    for t in hc.TASKS:
        family_counts[_family(t.id)] = family_counts.get(_family(t.id), 0) + 1
    meta = {
        "ok": True,
        "held_out_count": len(held_entries),
        "dev_count": len(dev_entries),
        "family_counts": family_counts,
        "manifest_sha256": digest,
        "manifest_path": str(MANIFEST_PATH.relative_to(ROOT)),
        "note": "pin is independent of dev/eval_gate.py and dev/factory.py; those only consume it",
    }
    META_PATH.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf8")
    print(json.dumps(meta, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
