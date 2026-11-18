"""TDD vertical slice tests for the bounded P4 ingest/coverage foundations.

Scope: lilguy.data.parse, lilguy.data.coverage, lilguy.data.fetch.
No real dataset download, no shell execution, offline only.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from lilguy.data import coverage as coverage_mod
from lilguy.data import fetch as fetch_mod
from lilguy.data.parse import ParseError, parse_command


# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------


def test_parse_simple_command_extracts_utility_and_flags():
    result = parse_command("grep -i foo file.txt")
    assert result["parse_ok"] is True
    assert result["utility"] == "grep"
    assert result["flags"].get("i") is True
    assert result["pipes"] == 0
    assert result["redirects"] == []
    assert result["subshells"] is False
    assert result["control_flow"] is False


def test_parse_combined_short_flags_known_utility():
    result = parse_command("ls -la")
    assert result["parse_ok"] is True
    assert result["flags"].get("l") is True
    assert result["flags"].get("a") is True


def test_parse_long_flag_with_value():
    result = parse_command("find . -maxdepth 2 -name '*.py'")
    assert result["parse_ok"] is True
    assert result["utility"] == "find"
    assert "maxdepth" in result["flags"]
    assert "name" in result["flags"]


def test_parse_counts_pipes():
    result = parse_command("cat file.txt | grep foo | sort")
    assert result["parse_ok"] is True
    assert result["pipes"] == 2


def test_parse_detects_redirects():
    result = parse_command("echo hi > out.txt 2>> err.log")
    assert result["parse_ok"] is True
    assert len(result["redirects"]) == 2


def test_parse_detects_subshell():
    result = parse_command("(cd /tmp && ls)")
    assert result["parse_ok"] is True
    assert result["subshells"] is True


def test_parse_detects_control_flow():
    result = parse_command("if [ -f a ]; then echo yes; fi")
    assert result["parse_ok"] is True
    assert result["control_flow"] is True


def test_parse_unparseable_command_sets_parse_ok_false():
    result = parse_command("echo 'unterminated")
    assert result["parse_ok"] is False
    assert result["utility"] is None


def test_parse_command_never_executes(monkeypatch):
    # Guard: parse must not invoke subprocess/os.system under any input.
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    parse_command("rm -rf / ; echo pwned")
    assert calls == []


def test_parse_command_raises_on_non_string_input():
    with pytest.raises(ParseError):
        parse_command(None)  # type: ignore[arg-type]


def test_parse_command_conservative_on_arbitrary_utility_negative_flag():
    # Utility not in the known table: do not interpret combined chars as flags,
    # but also never drop the token silently -- keep it as one unsplit flag.
    result = parse_command("mysteryutil -xyz")
    assert result["parse_ok"] is True
    assert result["utility"] == "mysteryutil"
    assert result["flags"] == {"xyz": True}


def test_parse_dash_dash_stops_flag_parsing():
    result = parse_command("grep -i -- -foo file.txt")
    assert result["flags"] == {"i": True}


def test_parse_attached_short_flag_value_not_split_into_digits():
    result = parse_command("head -n10 file.txt")
    assert result["flags"] == {"n": "10"}


def test_parse_grep_value_flag_consumes_next_token_not_a_flag():
    result = parse_command("grep -e foo -A 3 file.txt")
    assert result["flags"]["e"] == "foo"
    assert result["flags"]["A"] == "3"


def test_parse_find_value_flag_glob_argument_kept_as_value():
    result = parse_command("find . -name '-weird*'")
    assert result["flags"]["name"] == "-weird*"


def test_parse_pipeline_records_every_stage_as_a_command():
    result = parse_command("grep foo file | rm -rf x")
    utilities = [c["utility"] for c in result["commands"]]
    assert utilities == ["grep", "rm"]


def test_parse_command_substitution_flagged():
    result = parse_command("echo $(ls -la)")
    assert result["cmd_substitution"] is True
    assert "ls" not in result["utilities"]


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


TOOLSET_FIXTURE = {
    "grep": ["i", "v", "r"],
    "ls": ["l", "a"],
    "sort": ["r", "n"],
    "find": ["name", "type"],
}


def _rec(source, cmd):
    return {"source": source, "cmd": cmd}


def test_coverage_reports_utility_and_flag_frequency():
    records = [
        _rec("tldr", "grep -i foo"),
        _rec("tldr", "grep -v bar"),
        _rec("nl2sh-alfa", "ls -la"),
    ]
    report = coverage_mod.coverage(records, TOOLSET_FIXTURE)
    assert report["utility_frequency"]["grep"] == 2
    assert report["utility_frequency"]["ls"] == 1
    assert report["flag_frequency"]["grep"]["i"] == 1
    assert report["flag_frequency"]["grep"]["v"] == 1


def test_coverage_per_source_breakdown():
    records = [_rec("tldr", "grep -i foo"), _rec("nl2sh-alfa", "ls -la")]
    report = coverage_mod.coverage(records, TOOLSET_FIXTURE)
    assert report["per_source"]["tldr"]["utility_frequency"]["grep"] == 1
    assert report["per_source"]["nl2sh-alfa"]["utility_frequency"]["ls"] == 1


def test_coverage_parse_failure_rate():
    records = [
        _rec("tldr", "grep -i foo"),
        _rec("tldr", "echo 'unterminated"),
    ]
    report = coverage_mod.coverage(records, TOOLSET_FIXTURE)
    assert report["parse_failure_rate"] == pytest.approx(0.5)


def test_coverage_counts_covered_vs_uncovered_flags():
    records = [
        _rec("tldr", "grep -i foo"),
        _rec("tldr", "grep -z foo"),  # -z not in toolset for grep
    ]
    report = coverage_mod.coverage(records, TOOLSET_FIXTURE)
    assert report["covered_count"] >= 1
    assert any(u == "grep" and f == "z" for u, f in report["top_uncovered"])


def test_coverage_excludes_redirects_and_subshells_from_covered():
    records = [_rec("tldr", "echo hi > out.txt"), _rec("tldr", "(ls)")]
    report = coverage_mod.coverage(records, TOOLSET_FIXTURE)
    # redirects/subshells/control-flow never contribute to 'covered' accounting
    assert "redirect" not in report["utility_frequency"]
    assert "subshell" not in report["utility_frequency"]


def test_coverage_requires_toolset_mapping():
    with pytest.raises(ValueError):
        coverage_mod.coverage([_rec("tldr", "grep -i foo")], toolset=None)  # type: ignore[arg-type]


def test_coverage_half_supported_flags_not_covered():
    # grep -iz: 'i' is supported, 'z' is not -> whole record uncovered.
    report = coverage_mod.coverage([_rec("tldr", "grep -iz foo")], TOOLSET_FIXTURE)
    assert report["covered_count"] == 0


def test_coverage_pipeline_partial_support_not_covered():
    # grep is supported, rm is not: record-level coverage must require ALL
    # stages supported, not just the first/leading one.
    report = coverage_mod.coverage([_rec("tldr", "grep foo file | rm -rf x")], TOOLSET_FIXTURE)
    assert report["covered_count"] == 0


def test_coverage_subshell_never_covered():
    report = coverage_mod.coverage([_rec("tldr", "(ls)")], TOOLSET_FIXTURE)
    assert report["covered_count"] == 0


def test_coverage_unknown_flags_not_covered():
    report = coverage_mod.coverage([_rec("tldr", "ls -lZ")], TOOLSET_FIXTURE)
    assert report["covered_count"] == 0


def test_coverage_command_substitution_never_covered():
    report = coverage_mod.coverage([_rec("tldr", "echo $(ls -la)")], TOOLSET_FIXTURE)
    assert report["covered_count"] == 0


def test_coverage_fully_supported_record_is_covered():
    report = coverage_mod.coverage([_rec("tldr", "grep -i foo")], TOOLSET_FIXTURE)
    assert report["covered_count"] == 1


def test_coverage_denominator_includes_parse_failures():
    records = [_rec("tldr", "grep -i foo"), _rec("tldr", "echo 'unterminated")]
    report = coverage_mod.coverage(records, TOOLSET_FIXTURE)
    assert report["total_records"] == 2
    assert report["covered_count"] <= report["total_records"]


def test_coverage_accepts_structured_toolset_schema():
    structured = {
        "tools": {
            "fs.grep": {"bash": {"utility": "grep", "flags": ["i", "v"]}},
        },
        "pipe": {"stages": ["grep"]},
    }
    report = coverage_mod.coverage([_rec("tldr", "grep -i foo")], structured)
    assert report["covered_count"] == 1


def test_coverage_reports_unsupported_structures():
    records = [_rec("tldr", "(ls)"), _rec("tldr", "if true; then ls; fi")]
    report = coverage_mod.coverage(records, TOOLSET_FIXTURE)
    assert report["unsupported_structures"].get("subshell") == 1
    assert report["unsupported_structures"].get("control_flow") == 1


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def test_fetch_refuses_history_source():
    with pytest.raises(ValueError):
        fetch_mod.fetch_records(source="history", config="train", limit=10)


def test_fetch_rejects_unknown_source():
    with pytest.raises(ValueError):
        fetch_mod.fetch_records(source="not-a-real-source", config="train", limit=10)


def test_fetch_normalizes_record_shape(monkeypatch):
    raw_rows = [
        {"nl": "list files", "bash": "ls -la", "split": "train"},
    ]

    def fake_loader(source, config):
        return raw_rows

    monkeypatch.setattr(fetch_mod, "_load_raw_rows", fake_loader)
    records = fetch_mod.fetch_records(source="nl2sh-alfa", config="train", limit=10)
    assert len(records) == 1
    rec = records[0]
    for key in (
        "id",
        "source",
        "orig_split",
        "verified",
        "nl",
        "cmd",
        "alt_cmds",
        "difficulty",
        "license",
    ):
        assert key in rec
    assert rec["source"] == "nl2sh-alfa"
    assert rec["license"] == "unverified"
    assert rec["nl"] == "list files"
    assert rec["cmd"] == "ls -la"


def test_fetch_respects_limit(monkeypatch):
    raw_rows = [{"nl": f"task {i}", "bash": "echo hi", "split": "train"} for i in range(5)]
    monkeypatch.setattr(fetch_mod, "_load_raw_rows", lambda source, config: raw_rows)
    records = fetch_mod.fetch_records(source="nl2sh-alfa", config="train", limit=2)
    assert len(records) == 2


def test_fetch_validates_missing_required_columns(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_load_raw_rows", lambda source, config: [{"only_col": "x"}])
    with pytest.raises(ValueError):
        fetch_mod.fetch_records(source="nl2sh-alfa", config="train", limit=10)


def test_fetch_tldr_source_maps_columns(monkeypatch):
    raw_rows = [{"nl": "copy a file", "cmd": "cp a b", "split": "test"}]
    monkeypatch.setattr(fetch_mod, "_load_raw_rows", lambda source, config: raw_rows)
    records = fetch_mod.fetch_records(source="tldr", config="test", limit=10)
    assert records[0]["source"] == "tldr"
    assert records[0]["orig_split"] == "test"
    assert records[0]["cmd"] == "cp a b"


def test_fetch_tldr_rejects_bash_shaped_row_missing_cmd(monkeypatch):
    # tldr rows use 'cmd', not 'bash' -- a bash-shaped row must fail loudly,
    # not be silently coerced the way nl2sh-alfa rows are.
    raw_rows = [{"nl": "copy a file", "bash": "cp a b", "split": "test"}]
    monkeypatch.setattr(fetch_mod, "_load_raw_rows", lambda source, config: raw_rows)
    with pytest.raises(ValueError):
        fetch_mod.fetch_records(source="tldr", config="test", limit=10)


def test_fetch_does_not_materialize_more_than_limit(monkeypatch):
    seen = {"count": 0}

    def exploding_generator():
        for i in range(10_000_000):
            seen["count"] += 1
            yield {"nl": f"task {i}", "bash": "echo hi", "split": "train"}

    monkeypatch.setattr(fetch_mod, "_load_raw_rows", lambda source, config: exploding_generator())
    records = fetch_mod.fetch_records(source="nl2sh-alfa", config="train", limit=3)
    assert len(records) == 3
    assert seen["count"] == 3  # lazy: never pulled past the limit


def test_fetch_rejects_empty_nl_field(monkeypatch):
    monkeypatch.setattr(
        fetch_mod, "_load_raw_rows", lambda source, config: [{"nl": "   ", "bash": "ls"}]
    )
    with pytest.raises(ValueError):
        fetch_mod.fetch_records(source="nl2sh-alfa", config="train", limit=10)


def test_fetch_missing_datasets_dependency_raises_clear_error(monkeypatch):
    # Simulate the optional 'datasets' package not being importable.
    def raiser(source, config):
        raise ImportError("datasets package is required for fetch; install lilguy[data]")

    monkeypatch.setattr(fetch_mod, "_load_raw_rows", raiser)
    with pytest.raises(ImportError):
        fetch_mod.fetch_records(source="nl2sh-alfa", config="train", limit=10)


def test_fetch_cli_help_smoke_without_data_deps():
    proc = subprocess.run(
        [sys.executable, "-m", "lilguy.data.fetch", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "--source" in proc.stdout


def test_fetch_cli_rejects_history_source_without_running():
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "lilguy.data.fetch",
            "--source",
            "history",
            "--config",
            "train",
            "--limit",
            "1",
            "--out",
            "/tmp/should-not-be-created.jsonl",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0


def test_fetch_writes_jsonl_cache(monkeypatch, tmp_path):
    raw_rows = [{"nl": "list files", "bash": "ls -la", "split": "train"}]
    monkeypatch.setattr(fetch_mod, "_load_raw_rows", lambda source, config: raw_rows)
    out_path = tmp_path / "out.jsonl"
    fetch_mod.write_jsonl(fetch_mod.fetch_records(source="nl2sh-alfa", config="train", limit=10), out_path)
    lines = out_path.read_text().strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["cmd"] == "ls -la"
