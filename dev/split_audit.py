"""Pure offline split-audit helper for future factory manifests.

Detects, in a manifest of entries assigned to splits (e.g. train/val/test), the leaks that would
make held-out evaluation meaningless:

  * cross-split shared template IDs       -- same ``template_id`` appears in 2+ splits
  * duplicate requests                    -- identical ``request`` text reused across entries
  * duplicate fixtures                    -- identical ``files`` dict reused across entries
  * near-duplicate request+fixture pairs  -- same shape after a simple renamed-path/value
                                              normalization (catches lazy variants of one item)

This module is pure stdlib, does no I/O beyond reading the manifest path handed to it, makes no
network calls, and never executes, trains, or evaluates anything. It only ever reports *reasons*
and *entry ids* -- never raw request/fixture content -- so audit output itself can't leak a
held-out item's substance into a log.

Minimal manifest contract
--------------------------
A manifest is JSON: a list of entry objects, or ``{"entries": [...]}``. Each entry must have:

  id          : str, unique within the manifest
  split       : str, non-empty (e.g. "train", "val", "test")
  request     : str, the natural-language task text
  files       : dict[str, str], relative path -> initial file text (may be empty {})

Optional:
  template_id : str, identifies the generating template/prototype. Entries that intentionally
                share one template across splits (e.g. a dev-only paired fixture, as in
                dev/fast12.py's ``ambiguous_config_pair``) must not appear in different splits of
                a *production* manifest; this module has no notion of "intentionally paired" and
                will flag any cross-split template_id reuse as a leak. Keeping dev fixtures in
                their own manifest (never fed to this auditor) is the caller's job.

Anything else on an entry is ignored. Malformed entries (wrong types, missing required fields,
duplicate ids) make the whole manifest invalid -- this module refuses to silently skip bad rows.

Limits (explicit)
------------------
  * Near-duplicate detection is a *simple* structural normalizer (strips digits, hex-ish runs, and
    common path separators from strings before hashing) -- it is not a semantic/embedding
    similarity check and will miss paraphrases that don't touch literal tokens/paths.
  * Template-id tracking can only catch leaks the manifest already labels with template_id; it does
    not infer templates from content.
  * This module makes no claim about *production readiness* of any manifest; it is a necessary,
    not sufficient, offline guard. It must not be used to approve building production data on its
    own.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field


REQUIRED_FIELDS = ("id", "split", "request", "files")


class ManifestError(ValueError):
    """Raised for a structurally malformed manifest (not a leak -- a contract violation)."""


@dataclass(frozen=True)
class Entry:
    id: str
    split: str
    request: str
    files: dict
    template_id: str | None = None


@dataclass
class AuditReport:
    """Result of auditing a manifest. ``ok`` is False iff any reason was recorded.

    Every reason references entry ids, never raw request/fixture text.
    """
    reasons: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reasons

    def add(self, reason: str) -> None:
        self.reasons.append(reason)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "reasons": list(self.reasons)}


# --- manifest parsing -----------------------------------------------------------------------


def parse_manifest(raw: str) -> list:
    """Parse manifest JSON text into a list of Entry. Raises ManifestError on any contract
    violation. Never catches exceptions silently -- malformed input must fail loudly."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        if "entries" not in data:
            raise ManifestError("manifest object must have an 'entries' key")
        data = data["entries"]

    if not isinstance(data, list):
        raise ManifestError("manifest must be a list of entries or {'entries': [...]}")
    if not data:
        raise ManifestError("manifest has no entries")

    entries = []
    seen_ids = set()
    for i, raw_entry in enumerate(data):
        if not isinstance(raw_entry, dict):
            raise ManifestError(f"entry at index {i} is not an object")
        for field_name in REQUIRED_FIELDS:
            if field_name not in raw_entry:
                raise ManifestError(f"entry at index {i} missing required field '{field_name}'")

        entry_id = raw_entry["id"]
        split = raw_entry["split"]
        request = raw_entry["request"]
        files = raw_entry["files"]
        template_id = raw_entry.get("template_id")

        if not isinstance(entry_id, str) or not entry_id:
            raise ManifestError(f"entry at index {i} has a non-string/empty id")
        if not isinstance(split, str) or not split:
            raise ManifestError(f"entry '{entry_id}' has a non-string/empty split")
        if not isinstance(request, str) or not request:
            raise ManifestError(f"entry '{entry_id}' has a non-string/empty request")
        if not isinstance(files, dict):
            raise ManifestError(f"entry '{entry_id}' has a non-dict 'files'")
        for path, text in files.items():
            if not isinstance(path, str) or not isinstance(text, str):
                raise ManifestError(f"entry '{entry_id}' has a non-string path/content in 'files'")
        if template_id is not None and not isinstance(template_id, str):
            raise ManifestError(f"entry '{entry_id}' has a non-string template_id")

        if entry_id in seen_ids:
            raise ManifestError(f"duplicate entry id '{entry_id}'")
        seen_ids.add(entry_id)

        entries.append(Entry(id=entry_id, split=split, request=request, files=files,
                              template_id=template_id))

    return entries


# --- normalization for near-duplicate detection ---------------------------------------------

_DIGITS_RE = re.compile(r"\d+")
_HEXISH_RE = re.compile(r"\b[0-9a-fA-F]{6,}\b")
_PATH_SEP_RE = re.compile(r"[\\/]+")


def _normalize_text(text: str) -> str:
    """Collapse the kind of trivial renamed-path/value edits a lazy variant uses (numbers,
    hex-ish ids, path separators) so the remaining skeleton can be compared. Intentionally
    shallow: see module docstring 'Limits'."""
    text = _HEXISH_RE.sub("<HEX>", text)
    text = _DIGITS_RE.sub("<NUM>", text)
    text = _PATH_SEP_RE.sub("/", text)
    return text.strip().lower()


def _normalize_files(files: dict) -> tuple:
    """Normalize a files dict into an order-independent, path/value-normalized signature."""
    items = []
    for path, text in files.items():
        items.append((_normalize_text(path), _normalize_text(text)))
    return tuple(sorted(items))


def _exact_files_key(files: dict) -> tuple:
    return tuple(sorted(files.items()))


# --- the audit checks ------------------------------------------------------------------------


def _check_template_ids(entries: list, report: AuditReport) -> None:
    by_template: dict = {}
    for e in entries:
        if e.template_id is None:
            continue
        by_template.setdefault(e.template_id, {}).setdefault(e.split, []).append(e.id)
    for template_id, split_map in by_template.items():
        if len(split_map) > 1:
            parts = ", ".join(
                f"{split}:[{','.join(sorted(ids))}]" for split, ids in sorted(split_map.items())
            )
            report.add(
                f"cross_split_template_id: template_id '{template_id}' appears in multiple "
                f"splits -- {parts}"
            )


def _allowed_dev_pair(group, pairs):
    return (len(group) == 2 and all(e.split == 'dev' for e in group)
            and frozenset(e.id for e in group) in pairs)


def _check_duplicate_requests(entries: list, report: AuditReport, pairs=()) -> None:
    by_request: dict = {}
    for e in entries:
        by_request.setdefault(e.request, []).append(e)
    for group in by_request.values():
        if len(group) > 1 and not _allowed_dev_pair(group, pairs):
            ids = [e.id for e in group]
            report.add(f"duplicate_request: entries share identical request text -- {sorted(ids)}")


def _check_duplicate_fixtures(entries: list, report: AuditReport, pairs=()) -> None:
    by_files: dict = {}
    for e in entries:
        by_files.setdefault(_exact_files_key(e.files), []).append(e)
    for group in by_files.values():
        if len(group) > 1 and not _allowed_dev_pair(group, pairs):
            ids = [e.id for e in group]
            report.add(f"duplicate_fixture: entries share identical files fixture -- {sorted(ids)}")


def _check_near_duplicates(entries: list, report: AuditReport) -> None:
    by_shape: dict = {}
    for e in entries:
        key = (_normalize_text(e.request), _normalize_files(e.files))
        by_shape.setdefault(key, []).append(e.id)
    for ids in by_shape.values():
        if len(ids) > 1:
            # exclude pairs already flagged as exact duplicates to keep reasons non-redundant
            group_entries = [e for e in entries if e.id in ids]
            exact = (
                len({e.request for e in group_entries}) == 1
                and len({_exact_files_key(e.files) for e in group_entries}) == 1
            )
            if exact:
                continue
            report.add(
                f"near_duplicate_request_fixture: entries match after renamed-path/value "
                f"normalization -- {sorted(ids)}"
            )


def _check_near_duplicates_cross_split(entries: list, report: AuditReport) -> None:
    """Near-duplicates are most dangerous when they straddle a split boundary (a held-out item
    whose 'different' variant leaked into train). Flag that specifically in addition to the
    general near-duplicate check above."""
    by_shape: dict = {}
    for e in entries:
        key = (_normalize_text(e.request), _normalize_files(e.files))
        by_shape.setdefault(key, []).append(e)
    for group in by_shape.values():
        if len(group) < 2:
            continue
        splits = {e.split for e in group}
        if len(splits) > 1:
            ids = sorted(e.id for e in group)
            split_parts = ", ".join(f"{s}:[{','.join(sorted(e.id for e in group if e.split == s))}]"
                                     for s in sorted(splits))
            report.add(
                f"cross_split_near_duplicate: near-duplicate request+fixture spans splits -- "
                f"{split_parts} (ids {ids})"
            )


def audit(entries: list, *, dev_request_pairs=(), dev_fixture_pairs=()) -> AuditReport:
    """Run every check against an already-parsed entry list and return the combined report."""
    report = AuditReport()
    _check_template_ids(entries, report)
    _check_duplicate_requests(entries, report, dev_request_pairs)
    _check_duplicate_fixtures(entries, report, dev_fixture_pairs)
    _check_near_duplicates(entries, report)
    _check_near_duplicates_cross_split(entries, report)
    return report


def audit_manifest_text(raw: str) -> AuditReport:
    """Parse + audit in one step. Raises ManifestError for malformed input (caller decides how
    to surface that; the CLI below turns it into a nonzero exit + a reasons-shaped message)."""
    entries = parse_manifest(raw)
    return audit(entries)


# --- CLI -----------------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="split_audit",
        description="Offline audit of a factory manifest for cross-split leaks and duplicate "
                     "fixtures. Reports reasons and entry ids only, never raw content. "
                     "Exits nonzero on any detected leak or malformed manifest.",
    )
    parser.add_argument("manifest", help="path to manifest JSON file")
    args = parser.parse_args(argv)

    try:
        with open(args.manifest, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as exc:
        print(json.dumps({"ok": False, "reasons": [f"io_error: {exc}"]}, indent=2))
        return 2

    try:
        report = audit_manifest_text(raw)
    except ManifestError as exc:
        print(json.dumps({"ok": False, "reasons": [f"malformed_manifest: {exc}"]}, indent=2))
        return 2

    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
