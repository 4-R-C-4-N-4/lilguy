"""The installed runtime must have no host-executor escape hatch.

These checks never import or invoke the retired host executor.
"""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from lilguy import cli
from lilguy.digest import digest
from lilguy.memory import ConventionStore, Entry


@pytest.mark.parametrize("module", [
    "agent", "actions", "shell", "backends", "eval", "policy.legacy",
])
def test_host_executor_modules_are_absent(module):
    assert importlib.util.find_spec(f"lilguy.{module}") is None


@pytest.mark.parametrize("args", [
    ["run"], ["run", "--unsafe-legacy"], ["eval"], ["--unsafe-legacy"],
])
def test_retired_commands_are_rejected_before_execution(args):
    # Test only after absence is established: no legacy payload is ever supplied.
    assert importlib.util.find_spec("lilguy.agent") is None
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2


def test_public_help_lists_only_guarded_commands():
    result = subprocess.run([sys.executable, "-m", "lilguy", "--help"],
                            capture_output=True, text=True, check=True)
    assert "--unsafe-legacy" not in result.stdout
    assert "eval" not in result.stdout
    assert "{setup,demo,serve,stop,probe,sandbox-run,do,ask,diff,approve,deny,commit,undo,sessions}" in result.stdout


def test_stale_runtime_resources_are_absent():
    import lilguy
    root = Path(lilguy.__file__).parent
    assert not (root / "grammar.gbnf").exists()
    assert not (root / "data" / "tasks.json").exists()


def test_digester_exposes_failure_and_clips_output():
    result = digest(1, "\n".join(str(n) for n in range(100)),
                    "cat: missing: No such file or directory")
    assert result.outcome == "fail"
    assert "ENOENT(missing)" in result.tags
    assert "76 lines hidden" in result.text


def test_project_conventions_win_ties():
    store = ConventionStore([Entry({"test"}, "Run tests.", "global"),
                             Entry({"test"}, "Run tests.", "project")])
    assert store.retrieve("test")[0].scope == "project"


def test_conventions_resource_is_preserved():
    assert ConventionStore.load().entries
