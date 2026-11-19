"""Red-first unit tests for dev/split_audit.py.

Every detection category below is proven with a paired positive control (a leak that must
produce a nonempty `reasons` list naming the right ids) and a negative control (a structurally
similar but clean manifest that must audit ok). CLI tests check the subprocess exit code only
(0 clean, 1 leak, 2 malformed) and that stdout never echoes raw request/file text.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dev import split_audit as sa


SPLIT_AUDIT_PATH = Path(sa.__file__)


def entry(id, split, request, files=None, template_id=None):
    d = {"id": id, "split": split, "request": request, "files": files or {}}
    if template_id is not None:
        d["template_id"] = template_id
    return d


# --- manifest contract / parsing --------------------------------------------------------------


def test_parse_manifest_accepts_bare_list():
    entries = sa.parse_manifest(json.dumps([entry("a", "train", "do x")]))
    assert entries[0].id == "a"


def test_parse_manifest_accepts_entries_key():
    entries = sa.parse_manifest(json.dumps({"entries": [entry("a", "train", "do x")]}))
    assert entries[0].id == "a"


@pytest.mark.parametrize("raw", ["not json", "{", ""])
def test_parse_manifest_rejects_invalid_json(raw):
    with pytest.raises(sa.ManifestError):
        sa.parse_manifest(raw)


def test_parse_manifest_rejects_non_list_non_entries_object():
    with pytest.raises(sa.ManifestError):
        sa.parse_manifest(json.dumps({"foo": "bar"}))


def test_parse_manifest_rejects_empty_list():
    with pytest.raises(sa.ManifestError):
        sa.parse_manifest(json.dumps([]))


def test_parse_manifest_rejects_non_object_entry():
    with pytest.raises(sa.ManifestError):
        sa.parse_manifest(json.dumps(["not an object"]))


@pytest.mark.parametrize("missing", sa.REQUIRED_FIELDS)
def test_parse_manifest_rejects_missing_required_field(missing):
    e = entry("a", "train", "do x")
    del e[missing]
    with pytest.raises(sa.ManifestError):
        sa.parse_manifest(json.dumps([e]))


def test_parse_manifest_rejects_duplicate_ids():
    with pytest.raises(sa.ManifestError):
        sa.parse_manifest(json.dumps([
            entry("a", "train", "do x"),
            entry("a", "val", "do y"),
        ]))


def test_parse_manifest_rejects_non_string_files_values():
    e = entry("a", "train", "do x", files={"foo.txt": 5})
    with pytest.raises(sa.ManifestError):
        sa.parse_manifest(json.dumps([e]))


def test_parse_manifest_rejects_non_dict_files():
    e = entry("a", "train", "do x")
    e["files"] = "oops"
    with pytest.raises(sa.ManifestError):
        sa.parse_manifest(json.dumps([e]))


def test_parse_manifest_rejects_empty_id():
    with pytest.raises(sa.ManifestError):
        sa.parse_manifest(json.dumps([entry("", "train", "do x")]))


def test_parse_manifest_clean_entries_roundtrip():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "do x", files={"f.txt": "hi"}, template_id="t1"),
    ]))
    assert entries[0].template_id == "t1"
    assert entries[0].files == {"f.txt": "hi"}


# --- cross-split template_id -----------------------------------------------------------------


def test_cross_split_template_id_is_flagged():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "do x", template_id="shared"),
        entry("b", "test", "do y", template_id="shared"),
    ]))
    report = sa.audit(entries)
    assert not report.ok
    assert any("cross_split_template_id" in r and "a" in r and "b" in r for r in report.reasons)


def test_same_split_template_id_reuse_is_not_flagged():
    """Same template reused within one split (e.g. a dev-only paired fixture, never across
    splits) must not trip this check -- only cross-split reuse is a leak."""
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "do x", template_id="shared"),
        entry("b", "train", "do y", template_id="shared"),
    ]))
    report = sa.audit(entries)
    assert not any("cross_split_template_id" in r for r in report.reasons)


def test_no_template_id_is_not_flagged():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "do x"),
        entry("b", "test", "do y"),
    ]))
    report = sa.audit(entries)
    assert not any("template_id" in r for r in report.reasons)


# --- duplicate requests -----------------------------------------------------------------------


def test_duplicate_request_is_flagged():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "Set the timeout to 30."),
        entry("b", "test", "Set the timeout to 30."),
    ]))
    report = sa.audit(entries)
    assert not report.ok
    assert any("duplicate_request" in r and "a" in r and "b" in r for r in report.reasons)


def test_distinct_requests_are_not_flagged_as_duplicate():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "Set the timeout to 30."),
        entry("b", "test", "Rename the config key."),
    ]))
    report = sa.audit(entries)
    assert not any("duplicate_request" in r for r in report.reasons)


# --- duplicate fixtures -----------------------------------------------------------------------


def test_duplicate_fixture_is_flagged():
    files = {"notes.txt": "status: draft\n"}
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "edit notes", files=files),
        entry("b", "test", "edit notes differently", files=files),
    ]))
    report = sa.audit(entries)
    assert not report.ok
    assert any("duplicate_fixture" in r and "a" in r and "b" in r for r in report.reasons)


def test_distinct_fixtures_are_not_flagged_as_duplicate():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "edit notes", files={"notes.txt": "status: draft\n"}),
        entry("b", "test", "edit notes", files={"notes.txt": "status: live\n"}),
    ]))
    report = sa.audit(entries)
    assert not any("duplicate_fixture" in r for r in report.reasons)


# --- near-duplicate request+fixture (renamed-path/value variants) -----------------------------


def test_renamed_path_near_duplicate_is_flagged():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "Bump version in file_12.json to 1.1.0.",
              files={"config/v1.json": "version=1"}),
        entry("b", "test", "Bump version in file_99.json to 1.1.0.",
              files={"config/v2.json": "version=1"}),
    ]))
    report = sa.audit(entries)
    assert not report.ok
    reasons = " ".join(report.reasons)
    assert "near_duplicate_request_fixture" in reasons
    assert "a" in reasons and "b" in reasons


def test_cross_split_near_duplicate_is_flagged_specifically():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "Bump version in file_12.json to 1.1.0.",
              files={"config/v1.json": "version=1"}),
        entry("b", "test", "Bump version in file_99.json to 1.1.0.",
              files={"config/v2.json": "version=1"}),
    ]))
    report = sa.audit(entries)
    assert any("cross_split_near_duplicate" in r for r in report.reasons)


def test_near_duplicate_within_one_split_still_flagged_generally_not_cross_split():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "Bump version in file_12.json to 1.1.0.",
              files={"config/v1.json": "version=1"}),
        entry("b", "train", "Bump version in file_99.json to 1.1.0.",
              files={"config/v2.json": "version=1"}),
    ]))
    report = sa.audit(entries)
    assert any("near_duplicate_request_fixture" in r for r in report.reasons)
    assert not any("cross_split_near_duplicate" in r for r in report.reasons)


def test_structurally_different_entries_are_not_flagged_as_near_duplicate():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "Bump version in file_12.json to 1.1.0.",
              files={"config/v1.json": "version=1"}),
        entry("b", "test", "Rewrite the README introduction paragraph.",
              files={"README.md": "# Intro\nhello\n"}),
    ]))
    report = sa.audit(entries)
    assert report.ok


def test_exact_duplicate_not_double_reported_as_near_duplicate():
    """An exact duplicate is already reported by the exact checks; the near-duplicate check
    should not also report it (keeps reasons non-redundant)."""
    files = {"notes.txt": "status: draft\n"}
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "edit notes", files=files),
        entry("b", "test", "edit notes", files=files),
    ]))
    report = sa.audit(entries)
    assert not any("near_duplicate_request_fixture" in r for r in report.reasons)
    assert any("duplicate_request" in r for r in report.reasons)
    assert any("duplicate_fixture" in r for r in report.reasons)


# --- reasons never contain raw content --------------------------------------------------------


def test_reasons_never_echo_raw_request_or_file_content():
    secret_request = "SECRET_REQUEST_TOKEN_DO_NOT_LEAK"
    secret_content = "SECRET_FILE_TOKEN_DO_NOT_LEAK"
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", secret_request, files={"f.txt": secret_content}),
        entry("b", "test", secret_request, files={"f.txt": secret_content}),
    ]))
    report = sa.audit(entries)
    blob = json.dumps(report.to_dict())
    assert secret_request not in blob
    assert secret_content not in blob
    # but ids must be present so a human can look the leak up
    assert "a" in blob and "b" in blob


# --- a clean manifest passes every check (full negative control) ------------------------------


def test_clean_manifest_with_no_leaks_passes_every_check():
    entries = sa.parse_manifest(json.dumps([
        entry("a", "train", "Rename status in notes.txt.", files={"notes.txt": "status: draft\n"}),
        entry("b", "val", "Bump package version.", files={"package.json": '{"v":"1.0.0"}'}),
        entry("c", "test", "Rewrite README intro.", files={"README.md": "# intro\n"}),
    ]))
    report = sa.audit(entries)
    assert report.ok
    assert report.reasons == []


# --- CLI ---------------------------------------------------------------------------------------


def _run_cli(manifest_path):
    return subprocess.run(
        [sys.executable, str(SPLIT_AUDIT_PATH), str(manifest_path)],
        capture_output=True, text=True, timeout=30,
    )


def test_cli_exits_zero_on_clean_manifest(tmp_path):
    manifest = tmp_path / "clean.json"
    manifest.write_text(json.dumps([
        entry("a", "train", "Rename status flag.", files={"notes.txt": "status: draft\n"}),
        entry("b", "test", "Rewrite README intro.", files={"README.md": "# intro\n"}),
    ]))
    result = _run_cli(manifest)
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["reasons"] == []


def test_cli_exits_one_on_leak_and_reports_reasons_not_content(tmp_path):
    secret = "SECRET_PAYLOAD_SHOULD_NOT_APPEAR"
    manifest = tmp_path / "leaky.json"
    manifest.write_text(json.dumps([
        entry("a", "train", secret, template_id="shared"),
        entry("b", "test", secret, template_id="shared"),
    ]))
    result = _run_cli(manifest)
    assert result.returncode == 1
    assert secret not in result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert len(out["reasons"]) >= 1
    assert any("a" in r and "b" in r for r in out["reasons"])


def test_cli_exits_two_on_malformed_json(tmp_path):
    manifest = tmp_path / "broken.json"
    manifest.write_text("{not valid json")
    result = _run_cli(manifest)
    assert result.returncode == 2
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert any("malformed_manifest" in r for r in out["reasons"])


def test_cli_exits_two_on_missing_file(tmp_path):
    result = _run_cli(tmp_path / "does_not_exist.json")
    assert result.returncode == 2
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert any("io_error" in r for r in out["reasons"])


def test_cli_exits_two_on_contract_violation(tmp_path):
    manifest = tmp_path / "bad_contract.json"
    manifest.write_text(json.dumps([{"id": "a", "split": "train"}]))  # missing request/files
    result = _run_cli(manifest)
    assert result.returncode == 2
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert any("malformed_manifest" in r for r in out["reasons"])


def test_main_function_returns_same_codes_as_subprocess(tmp_path, capsys):
    manifest = tmp_path / "clean.json"
    manifest.write_text(json.dumps([
        entry("a", "train", "Do thing one.", files={"a.txt": "x"}),
        entry("b", "test", "Do thing two.", files={"b.txt": "y"}),
    ]))
    rc = sa.main([str(manifest)])
    assert rc == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["ok"] is True
