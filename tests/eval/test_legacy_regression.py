"""Frozen v0.1 controls: these are trusted fixtures, not dataset commands.

The legacy executor is not a sandbox. Never reuse this runner for downloaded data.
"""
import json
from pathlib import Path

import pytest

from lilguy.backends import Scripted
from lilguy.eval import DATA, run_task

TASKS = json.loads((DATA / "tasks.json").read_text())


def test_fixture_count_is_twelve():
    assert len(TASKS) == 12
    assert len({task["id"] for task in TASKS}) == 12


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task["id"])
def test_scripted_oracle_passes(task):
    result = run_task(task, lambda t: Scripted(t["oracle"]))
    assert result["pass"], result


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task["id"])
def test_null_agent_fails(task):
    result = run_task(task, lambda _: Scripted([{"action": "done", "arg": "nothing"}]))
    assert not result["pass"], result


def test_resources_are_present():
    from lilguy.backends import GRAMMAR
    from lilguy.memory import ConventionStore

    assert "root" in GRAMMAR
    assert ConventionStore.load().entries
    assert Path(DATA / "tasks.json").is_file()
