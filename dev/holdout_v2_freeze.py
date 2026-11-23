#!/usr/bin/env python3
"""Freeze held-out v2 (dev/holdout_v2.py) into a pinned manifest, after the overlap audit.

    .venv/bin/python dev/holdout_v2_freeze.py

The audit covers every development task (the 80-task roster and the v4 focus fixtures), every
revision-10 training episode, and held-out v1. It writes dev/holdout_v2_manifest.json,
dev/holdout_v2_manifest.sha256 (the digest of those exact bytes) and dev/holdout_v2_manifest.meta.json.
It writes nothing if any check fails. No model, no shell, no network.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dev import dev_focus, holdout_v2, split_audit, v2_corpus  # noqa: E402
from dev.broad_runner import development_rows  # noqa: E402

MANIFEST = ROOT / "dev" / "holdout_v2_manifest.json"
DIGEST = ROOT / "dev" / "holdout_v2_manifest.sha256"
META = ROOT / "dev" / "holdout_v2_manifest.meta.json"


def held_rows():
    return [dict(id=t.id, split="held-out", template_id=f"heldout2-{t.id.split('_')[1]}",
                 request=t.request, files=t.files) for t in holdout_v2.TASKS]


def other_rows():
    rows = [dict(r, split="dev") for r in development_rows()]
    rows += [dict(id=t.id, split="dev", template_id=t.id, request=t.request, files=t.files) for t in dev_focus.TASKS]
    rows += [dict(r, split="dev", id="v1-" + r["id"]) for r in json.loads((ROOT / "dev/holdout_manifest.json").read_text())]
    rows += [ex.manifest() for ex in v2_corpus.generate(revision=10)]
    return rows


def main() -> int:
    held = held_rows()
    if len(held) != 100 or len({r["id"] for r in held}) != 100:
        print("expected 100 distinct held-out v2 tasks", file=sys.stderr)
        return 1
    others = other_rows()
    entries = split_audit.parse_manifest(json.dumps(held + others))
    # Overlaps among development or training rows themselves are not this suite's business
    # (the corpus gate handles them); any finding that names a held-out v2 task is fatal.
    findings = [r for r in split_audit.audit(entries).reasons if "heldout2_" in r]
    if findings:
        print("overlap audit failed:\n" + "\n".join(findings), file=sys.stderr)
        return 1
    data = (json.dumps(held, indent=2, sort_keys=True) + "\n").encode("utf8")
    digest = hashlib.sha256(data).hexdigest()
    MANIFEST.write_bytes(data)
    DIGEST.write_text(f"{digest}  dev/holdout_v2_manifest.json\n")
    META.write_text(json.dumps({
        "held_out_count": len(held), "audited_against": len(others), "manifest_sha256": digest,
        "families": dict(sorted(Counter(r["template_id"] for r in held).items())),
        "ask_mode": len(holdout_v2.ASK), "interface": 4,
        "note": "frozen before any revision-10 or interface-v4 model ran on it; run once per candidate",
    }, indent=2, sort_keys=True) + "\n")
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
