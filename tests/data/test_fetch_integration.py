"""Real-source compatibility regressions; never execute downloaded loader scripts."""
import sys
from types import SimpleNamespace

from lilguy.data import fetch


def test_tldr_uses_packaged_json_loader_not_remote_repository_script(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "datasets", SimpleNamespace(load_dataset=lambda *a, **k: calls.append((a, k)) or []))
    assert list(fetch._load_raw_rows("tldr", "train")) == []
    assert calls[0][0] == ("json",)
    assert calls[0][1]["data_files"]["train"].endswith("/tldr-train.jsonl")
    assert calls[0][1]["split"] == "train"


def test_validation_split_is_allowed_for_tldr_but_not_alfa(monkeypatch):
    import pytest
    monkeypatch.setattr(fetch, "_load_raw_rows", lambda *_: [{"nl": "list", "cmd": "ls"}])
    assert len(fetch.fetch_records(source="tldr", config="validation", limit=1)) == 1
    with pytest.raises(ValueError):
        fetch.fetch_records(source="nl2sh-alfa", config="validation", limit=1)
