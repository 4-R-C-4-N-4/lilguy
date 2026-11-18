"""Additional public sources: loaded from raw files with built-in loaders, never remote scripts."""
import sys
from types import SimpleNamespace

import pytest

from lilguy.data import fetch


def _capture(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "datasets",
                        SimpleNamespace(load_dataset=lambda *a, **k: calls.append((a, k)) or []))
    return calls


@pytest.mark.parametrize("source,config,builder,needle", [
    ("cli-explained", "train", "json", "cli_commands_explained.json"),
    ("nl2bash-custom", "train", "json", "data/train.json"),
    ("nl2bash-custom", "validation", "json", "data/dev.json"),
    ("nl2bash-custom", "test", "json", "data/test.json"),
    ("bash6k", "train", "parquet", "data/train-00000-of-00001.parquet"),
])
def test_new_sources_use_builtin_loaders_on_raw_files(monkeypatch, source, config, builder, needle):
    calls = _capture(monkeypatch)
    assert list(fetch._load_raw_rows(source, config)) == []
    (args, kwargs), = calls
    assert args == (builder,)
    assert needle in list(kwargs["data_files"].values())[0]
    assert "dataset.py" not in str(kwargs)


@pytest.mark.parametrize("source,row,nl,cmd", [
    ("cli-explained", {"code": "mount | column -t", "title": "mounted filesystems", "description": "long"},
     "mounted filesystems", "mount | column -t"),
    ("cli-explained", {"code": "ls", "title": "", "description": "list files"}, "list files", "ls"),
    ("nl2bash-custom", {"bash_code": "find -type d", "nl_command": "Find all directories", "srno": 1},
     "Find all directories", "find -type d"),
    ("bash6k", {"prompt": "List all files", "completion": "ls -la\n"}, "List all files", "ls -la"),
])
def test_rows_normalize(monkeypatch, source, row, nl, cmd):
    monkeypatch.setattr(fetch, "_load_raw_rows", lambda *_: [row])
    (record,) = fetch.fetch_records(source=source, config="train", limit=10)
    assert (record["nl"], record["cmd"], record["source"]) == (nl, cmd, source)
    assert record["license"] == "unverified"


def test_rows_without_a_command_are_skipped_for_scraped_sources(monkeypatch):
    rows = [{"code": "", "title": "keyboard shortcut", "description": "x"},
            {"code": "ls", "title": "list", "description": ""}]
    monkeypatch.setattr(fetch, "_load_raw_rows", lambda *_: rows)
    assert [r["cmd"] for r in fetch.fetch_records(source="cli-explained", config="train", limit=10)] == ["ls"]


def test_single_split_sources_refuse_other_splits():
    with pytest.raises(ValueError):
        fetch.fetch_records(source="cli-explained", config="test", limit=1)
    with pytest.raises(ValueError):
        fetch.fetch_records(source="bash6k", config="validation", limit=1)
